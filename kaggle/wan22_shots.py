"""Render Wan 2.2 TI2V-5B clips on Kaggle from the jobs exported by `make shots-export`.

Kaggle notebook settings: Accelerator GPU T4 x2, Internet on. Add your export folder as a dataset.
In a cell:   !python /kaggle/input/<your-dataset>/wan22_shots.py      (or paste this file into a cell)
Output:      /kaggle/working/out/<shot>-<clip_key>.mp4 + runs_kaggle.jsonl
             -> download /kaggle/working/out and run `make shots-import DIR=<that folder>`

VERIFY the generate.py flags against https://github.com/Wan-Video/Wan2.2 before the first run.
T4s have 16 GB and no native bf16: expect to iterate (lower frame count, offloading, or Colab), and record
what happened in FAILURES.md. Clips that already exist are skipped, so a rerun resumes.
"""
import datetime
import glob
import json
import os
import subprocess
import sys
import time
import uuid

WORK = "/kaggle/working"
OUT = f"{WORK}/out"
TEMP = "/kaggle/temp"  # outside the 20 GB /kaggle/working limit; weights are 34 GB
REPO = f"{TEMP}/Wan2.2"
CKPT = f"{TEMP}/Wan2.2-TI2V-5B"
SAMPLE_STEPS = int(os.environ.get("WAN_STEPS", "40"))  # fewer steps = faster drafts

jobs_path = glob.glob("/kaggle/input/**/jobs.json", recursive=True)[0]
job_dir = os.path.dirname(jobs_path)
jobs = json.load(open(jobs_path))
os.makedirs(OUT, exist_ok=True)
os.makedirs(TEMP, exist_ok=True)
log_path = f"{OUT}/runs_kaggle.jsonl"


def sh(cmd, **kw):
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, **kw)


if not os.path.isdir(REPO):
    sh(["git", "clone", "--depth", "1", "https://github.com/Wan-Video/Wan2.2.git", REPO], check=True)
    reqs = [l for l in open(f"{REPO}/requirements.txt").read().splitlines() if l and "flash_attn" not in l]
    sh([sys.executable, "-m", "pip", "install", "-q", *reqs], check=True)  # flash_attn usually fails to build here
if not os.path.isdir(CKPT):
    sh([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub[cli]"], check=True)
    sh([sys.executable, "-c", f"from huggingface_hub import snapshot_download; snapshot_download('Wan-AI/Wan2.2-TI2V-5B', local_dir='{CKPT}')"], check=True)

# T4 has no flash-attn support: use wan.modules.attention.attention (falls back to torch SDPA)
model_py = f"{REPO}/wan/modules/model.py"
src = open(model_py).read()
if "import attention as flash_attention" not in src:
    open(model_py, "w").write(src.replace("from .attention import flash_attention", "from .attention import attention as flash_attention"))

for job in jobs:
    dest = f"{OUT}/{job['shot_id']}-{job['clip_key']}.mp4"
    if os.path.exists(dest):
        print(f"skip {dest} (exists)")
        continue
    cmd = [sys.executable, "generate.py", "--task", "ti2v-5B", "--size", job["size"], "--ckpt_dir", CKPT,
           "--offload_model", "True", "--convert_model_dtype", "--t5_cpu",
           "--image", os.path.join(job_dir, job["image"]), "--prompt", job["prompt"],
           "--base_seed", str(job["seed"]), "--frame_num", str(job["frame_num"]),
           "--sample_steps", str(SAMPLE_STEPS), "--save_file", dest]
    t0 = time.perf_counter()
    result = sh(cmd, cwd=REPO, capture_output=True, text=True)
    latency = round(time.perf_counter() - t0, 2)
    ok = result.returncode == 0 and os.path.exists(dest)
    rec = {"call_id": uuid.uuid4().hex[:12], "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "stage": "shots", "shot_id": job["shot_id"], "provider": "kaggle", "model": job["model"],
           "params": {"size": job["size"], "frame_num": job["frame_num"], "sample_steps": SAMPLE_STEPS, "gpu": "T4"},
           "seed": job["seed"], "cache_key": job["clip_key"], "attempt": 1, "usage": {}, "cost_usd": 0.0,
           "gpu_s": latency, "latency_s": latency, "status": "ok" if ok else "error",
           "output": os.path.basename(dest) if ok else None}
    if not ok:
        rec["error"] = (result.stderr or result.stdout)[-800:]
        print(rec["error"])
    with open(log_path, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"{job['shot_id']}: {'ok' if ok else 'FAILED'} in {latency}s", flush=True)

print(f"done. Download {OUT} (Output tab, or zip it) and run: make shots-import DIR=<folder>")
