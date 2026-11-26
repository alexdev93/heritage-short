"""Generate ACE-Step 1.5 score candidates on Kaggle or Colab from `make music-export`.

Notebook: GPU on, Internet on, the music export folder added as a dataset (or uploaded to Colab).
Output: /kaggle/working/music_out/cand_<seed>.wav + runs_kaggle.jsonl
        -> download and run `make music-import DIR=<that folder>`

ACE-Step 1.5 is installed with its own `uv sync` environment (torch 2.10 / CUDA 12.8, which still supports the T4),
so it cannot clash with Kaggle's preinstalled packages. Each candidate runs `uv run python` on a small helper.
We run the 2B turbo DiT only (no 5Hz language model, thinking=False): our caption, bpm and key are used exactly
as written instead of being rewritten by the LM, and it fits easily in one 16 GB T4 (float16, T4 has no bf16).
API: docs/en/INFERENCE.md in github.com/ace-step/ACE-Step-1.5 (AceStepHandler + GenerationParams + generate_music).
"""
import datetime
import glob
import json
import os
import shutil
import subprocess
import time
import uuid

OUT = "/kaggle/working/music_out" if os.path.isdir("/kaggle") else "/content/music_out"
job = json.load(open(glob.glob("/kaggle/input/**/jobs.json", recursive=True)[0] if os.path.isdir("/kaggle")
                     else "/content/jobs.json"))
os.makedirs(OUT, exist_ok=True)
log_path = f"{OUT}/runs_kaggle.jsonl"


ACE_DIR = "/kaggle/temp/ACE-Step-1.5" if os.path.isdir("/kaggle") else "/content/ACE-Step-1.5"
UV = os.path.expanduser("~/.local/bin/uv")
HELPER = f"{OUT}/_ace_one.py"

HELPER_SRC = r"""
import json, os, shutil, sys
from acestep.handler import AceStepHandler
from acestep.inference import GenerationParams, GenerationConfig, generate_music
a = json.loads(sys.argv[1])
dit = AceStepHandler()
msg, ok = dit.initialize_service(project_root=a["root"], config_path="acestep-v15-turbo", device="cuda")
if not ok:
    sys.exit("initialize_service failed: " + str(msg))
params = GenerationParams(
    caption=a["caption"], lyrics="[Instrumental]" if a["instrumental"] else (a["lyrics"] or ""),
    instrumental=a["instrumental"], bpm=a["bpm"], keyscale=a["key"], duration=float(a["duration_s"]),
    seed=a["seed"], thinking=False, use_cot_metas=False, use_cot_caption=False, use_cot_language=False)
config = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[a["seed"]], audio_format="wav")
result = generate_music(dit, None, params, config, save_dir=os.path.dirname(a["dest"]) + "/_tmp")
if not result.success:
    sys.exit("generate_music failed: " + str(result.error))
shutil.move(result.audios[0]["path"], a["dest"])
"""


def setup():
    """Install uv, clone ACE-Step 1.5 and `uv sync` its pinned environment. Weights download on first use."""
    if not os.path.exists(UV):
        # As root (Kaggle) the installer defaults to /usr/local/bin; pin it to where UV points.
        subprocess.run("curl -LsSf https://astral.sh/uv/install.sh | sh", shell=True, check=True,
                       env={**os.environ, "UV_INSTALL_DIR": os.path.dirname(UV)})
    if not os.path.isdir(ACE_DIR):
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/ACE-Step/ACE-Step-1.5.git", ACE_DIR], check=True)
    subprocess.run([UV, "sync"], cwd=ACE_DIR, check=True)
    with open(HELPER, "w") as f:
        f.write(HELPER_SRC)


def generate_one(caption, lyrics, instrumental, duration_s, bpm, key, seed, dest):
    """One candidate per seed. Tempo and key go in their own fields, not in the caption."""
    args = {"root": ACE_DIR, "caption": caption, "lyrics": lyrics, "instrumental": instrumental,
            "duration_s": duration_s, "bpm": bpm, "key": key, "seed": seed, "dest": dest}
    # Jupyter sets MPLBACKEND to its inline backend, which ACE-Step's own venv can't import.
    subprocess.run([UV, "run", "python", HELPER, json.dumps(args)], cwd=ACE_DIR, check=True,
                   env={**os.environ, "MPLBACKEND": "Agg"})
    shutil.rmtree(f"{OUT}/_tmp", ignore_errors=True)


setup()
for seed in job["seeds"]:
    dest = f"{OUT}/cand_{seed}.wav"
    if os.path.exists(dest):
        continue
    t0 = time.perf_counter()
    status, error = "ok", None
    try:
        generate_one(job["caption"], job.get("lyrics"), job["instrumental"], job["duration_s"], job["bpm"],
                     job["key"], seed, dest)
    except Exception as e:  # noqa: BLE001
        status, error = "error", f"{type(e).__name__}: {e}"[:800]
    latency = round(time.perf_counter() - t0, 2)
    rec = {"call_id": uuid.uuid4().hex[:12], "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "stage": "music", "shot_id": None, "provider": "kaggle", "model": job["model"],
           "params": {k: job[k] for k in ("caption", "bpm", "key", "duration_s", "instrumental")},
           "seed": seed, "cache_key": job["job_key"], "attempt": 1, "usage": {}, "cost_usd": 0.0,
           "gpu_s": latency, "latency_s": latency, "status": status, "output": os.path.basename(dest) if status == "ok" else None}
    if error:
        rec["error"] = error
    with open(log_path, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"seed {seed}: {status} in {latency}s", flush=True)
