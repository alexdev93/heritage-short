"""Smoke test: call every provider once, log latency to runs.jsonl, and report what works.

Run it first, and again whenever a free tier or model ID may have changed.
Usage: python -m pipeline.smoke
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import time
from pathlib import Path

from pipeline import common as C
from pipeline import config, providers

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"  {'✓' if ok else '✗'} {name}: {detail}", flush=True)


def check_tools() -> None:
    ok = sys.version_info >= (3, 10)
    record("python", ok, sys.version.split()[0] + ("" if ok else " (need 3.10+)"))
    if not shutil.which("ffmpeg"):
        record("ffmpeg", False, "not installed")
        return
    missing = [f for f in ("subtitles", "sidechaincompress", "zoompan", "loudnorm", "tpad") if not C.has_ffmpeg_filter(f)]
    record("ffmpeg", not missing, "all filters present" if not missing else f"missing filters: {missing}")


def suggest_models(keyword: str) -> None:
    try:
        from google import genai

        client = genai.Client(api_key=config.require("GEMINI_API_KEY"))
        names = [m.name for m in client.models.list() if keyword in m.name]
        if names:
            print(f"      models containing '{keyword}': {', '.join(n.split('/')[-1] for n in names[:15])}")
    except Exception as e:  # noqa: BLE001
        print(f"      (could not list models: {e})")


def gemini_text() -> None:
    model = config.MODELS["text"]
    t0 = time.perf_counter()
    try:
        with C.model_call("smoke", "gemini", model, {"task": "ping"}) as rec:
            text, usage = providers.gemini_text("Reply with the single word: ok", model)
            rec["usage"], rec["output"] = usage, text.strip()[:20]
        record(f"gemini text ({model})", True, f"{time.perf_counter() - t0:.1f}s, replied {text.strip()[:20]!r}")
    except BaseException as e:  # noqa: BLE001
        record(f"gemini text ({model})", False, str(e)[:200])
        suggest_models("flash")


def gemini_tts() -> None:
    model = config.MODELS["tts"]
    out = C.stage_dir("smoke") / "tts.wav"
    t0 = time.perf_counter()
    try:
        with C.model_call("smoke", "gemini", model, {"task": "tts_ping", "voice": "Kore"}) as rec:
            pcm, rate, usage = providers.gemini_tts("ሰላም። Hello.", "Kore", "Say warmly", model)
            providers.write_wav(out, pcm, rate)
            rec["usage"], rec["output"] = usage, C.rel(out)
        record(f"gemini tts ({model})", True, f"{time.perf_counter() - t0:.1f}s, {C.media_duration(out):.1f}s audio -> {C.rel(out)}")
    except BaseException as e:  # noqa: BLE001
        record(f"gemini tts ({model})", False, str(e)[:200])
        suggest_models("tts")


def cloudflare_image() -> None:
    from PIL import Image

    model = config.MODELS["image"]
    out = C.stage_dir("smoke") / "image.png"
    t0 = time.perf_counter()
    try:
        prompt = "a clay coffee pot (jebena) on a wooden stool, morning light"
        with C.model_call("smoke", "cloudflare", model, {"prompt": prompt, "steps": config.CF_IMAGE_STEPS}, seed=1) as rec:
            data, usage = providers.cf_image(prompt, 1, config.CF_IMAGE_STEPS, model)
            Image.open(io.BytesIO(data)).convert("RGB").save(out)
            rec["usage"], rec["output"] = usage, C.rel(out)
        size = Image.open(out).size
        record(f"cloudflare image ({model})", True, f"{time.perf_counter() - t0:.1f}s, {size[0]}x{size[1]} -> {C.rel(out)}")
    except BaseException as e:  # noqa: BLE001
        record(f"cloudflare image ({model})", False, str(e)[:200])


def kaggle() -> None:
    has_file = (Path.home() / ".kaggle" / "kaggle.json").exists() or (Path.home() / ".config" / "kaggle" / "kaggle.json").exists()
    has_env = bool(os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"))
    record("kaggle credentials", has_file or has_env,
           "found (optional: lets you upload datasets from the CLI)" if has_file or has_env else
           "not found — fine if you use the Kaggle website; phone-verify your account to get GPUs")


def main(argv=None) -> None:
    print("Smoke test" + (" (FAKE providers)" if C.FAKE else ""))
    check_tools()
    gemini_text()
    gemini_tts()
    cloudflare_image()
    kaggle()
    required = [(n, ok) for n, ok, _ in results if not n.startswith("kaggle")]
    failed = [n for n, ok in required if not ok]
    print(f"\n  {len(required) - len(failed)}/{len(required)} required checks passed (Kaggle credentials are optional). "
          f"Calls logged to {C.rel(C.RUNS)}.")
    if failed:
        print("  Fix the failures above (and note what you found in FAILURES.md / COSTS.md).")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
