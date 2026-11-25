"""Shared helpers: paths, storyboard I/O, hashing, manifests, call logging, retries, FFmpeg."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pipeline.config import ROOT

# PIPELINE_FAKE=1 swaps every model for a local stand-in and writes to outputs_fake/,
# so you can test the plumbing without spending quota. Real runs never read fake outputs.
FAKE = os.environ.get("PIPELINE_FAKE") == "1"
OUT = ROOT / ("outputs_fake" if FAKE else "outputs")
RUNS = OUT / "runs.jsonl" if FAKE else ROOT / "runs.jsonl"
STAGE_TIMES = OUT / "stage_times.jsonl"
STORYBOARD = ROOT / os.environ.get("STORYBOARD", "storyboard.json")
SCHEMA = ROOT / "schema" / "storyboard.schema.json"


# ---------- console ----------

def info(msg: str) -> None:
    print(f"  {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"  ✗ {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


# ---------- hashing ----------

def sha(obj) -> str:
    """Stable 12-char hash of any JSON-able object. Used as the cache key."""
    data = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:12]


def file_sha(path: str | Path | None) -> str | None:
    if not path:
        return None
    p = ROOT / path if not Path(path).is_absolute() else Path(path)
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


# ---------- storyboard ----------

_warned: set[str] = set()

def load_storyboard(validate: bool = True, require_consent: bool = False) -> dict:
    if not STORYBOARD.exists():
        die(f"{rel(STORYBOARD)} not found.")
    try:
        sb = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"{rel(STORYBOARD)} is not valid JSON: {e}")
    if validate:
        from pipeline.validate import check

        errors, warnings, consent = check(sb)
        if require_consent and not FAKE:
            errors = errors + consent
        else:
            warnings = warnings + consent
        for w in warnings:
            if w not in _warned:  # each warning once per run, not once per stage
                warn(w)
                _warned.add(w)
        if errors:
            for e in errors:
                print(f"  ✗ {e}", file=sys.stderr)
            die("storyboard.json failed validation; fix it and rerun.")
    return sb


def save_storyboard(sb: dict) -> None:
    backup_dir = OUT / "storyboard_history"
    backup_dir.mkdir(parents=True, exist_ok=True)
    if STORYBOARD.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(STORYBOARD, backup_dir / f"storyboard-{stamp}.json")
    STORYBOARD.write_text(json.dumps(sb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def timeline(sb: dict) -> tuple[list[tuple[dict, float]], float]:
    """[(shot, start_s), ...] and the total length of the shots (end card excluded)."""
    t, out = 0.0, []
    for shot in sb["shots"]:
        out.append((shot, t))
        t += float(shot["duration_s"])
    return out, t


def total_length(sb: dict) -> float:
    return timeline(sb)[1] + float(sb["end_card"]["duration_s"])


# ---------- manifests: what each stage produced for the current storyboard ----------

class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def get(self, key: str):
        return self.data.get(key)

    def set(self, key: str, value: dict) -> None:
        self.data[key] = value

    def drop(self, key: str) -> None:
        self.data.pop(key, None)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def stage_dir(name: str) -> Path:
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- logging: one line per model call in runs.jsonl ----------

def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@contextmanager
def model_call(stage: str, provider: str, model: str, params: dict, *, shot_id: str | None = None,
               seed: int | None = None, cache_key: str | None = None, attempt: int = 1):
    """Wrap every model call. Records model, params, seed, latency, usage, status and output.

    Inside the block, set rec["output"] and rec["usage"] (e.g. {"images": 1} or {"tokens_in": 120}).
    """
    rec = {
        "call_id": uuid.uuid4().hex[:12],
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stage": stage,
        "shot_id": shot_id,
        "provider": "fake" if FAKE else provider,
        "model": model,
        "params": params,
        "seed": seed,
        "cache_key": cache_key,
        "attempt": attempt,
        "usage": {},
        "cost_usd": 0.0,  # actual spend; free tiers are 0. List-price equivalents are computed in costs.py.
        "output": None,
    }
    t0 = time.perf_counter()
    try:
        yield rec
        rec["status"] = "ok"
    except BaseException as e:  # noqa: BLE001 - we re-raise after logging
        rec["status"] = "error"
        rec["error"] = f"{type(e).__name__}: {e}"[:500]
        raise
    finally:
        rec["latency_s"] = round(time.perf_counter() - t0, 3)
        append_jsonl(RUNS, rec)


@contextmanager
def stage_timer(stage: str, **extra):
    t0 = time.perf_counter()
    yield
    append_jsonl(STAGE_TIMES, {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "stage": stage, "seconds": round(time.perf_counter() - t0, 2), **extra})


# ---------- retries ----------

class RetryableError(RuntimeError):
    """Raise for quota (429), overload (5xx) and network errors."""


RETRY_CODES = {408, 429, 500, 502, 503, 504}


def is_retryable(e: BaseException) -> bool:
    if isinstance(e, RetryableError):
        return True
    for attr in ("code", "status_code"):
        if getattr(e, attr, None) in RETRY_CODES:
            return True
    name = type(e).__name__
    return name in {"ConnectionError", "Timeout", "ReadTimeout", "ConnectTimeout", "ServerError"}


def retry_after_s(message: str) -> float | None:
    """Seconds from 'retry in 43s' / 'retry in 11h37m56s' in an error message, or None."""
    m = re.search(r"retry in ((?:\d+(?:\.\d+)?[hms])+)", message, re.IGNORECASE)
    if not m:
        return None
    unit = {"h": 3600, "m": 60, "s": 1}
    return sum(float(n) * unit[u.lower()] for n, u in re.findall(r"(\d+(?:\.\d+)?)([hms])", m.group(1), re.IGNORECASE))


def with_retries(fn, attempts: int = 4, base: float = 2.0):
    """Call fn(attempt_number). Retries retryable errors with exponential backoff and jitter."""
    for i in range(1, attempts + 1):
        try:
            return fn(i)
        except Exception as e:  # noqa: BLE001
            if i == attempts or not is_retryable(e):
                raise
            delay = base ** i + random.uniform(0, 1)
            hint = retry_after_s(str(e))
            if hint is not None:  # rate limits say how long to wait ("Please retry in 43s", F7)
                if hint > 300:  # a daily quota ("retry in 11h37m56s"): waiting won't help today
                    raise RuntimeError(f"quota exhausted, provider says retry in {hint / 3600:.1f} h: {str(e)[:200]}") from e
                delay = max(delay, hint + 1)
            warn(f"{type(e).__name__}: {str(e)[:120]} — retry {i}/{attempts - 1} in {delay:.1f}s")
            time.sleep(delay)


# ---------- FFmpeg ----------

def ffmpeg(*args: str) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        die("ffmpeg failed:\n  " + " ".join(cmd) + "\n" + result.stderr[-2000:])


def media_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        die(f"could not read duration of {path}: {out.stderr.strip()}")
        return 0.0


def has_ffmpeg_filter(name: str) -> bool:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return any(line.split()[1:2] == [name] for line in out.stdout.splitlines() if line.strip())
