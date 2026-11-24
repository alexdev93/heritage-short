"""Generate ACE-Step 1.5 score candidates on Kaggle or Colab from `make music-export`.

Notebook: GPU on, Internet on, the music export folder added as a dataset (or uploaded to Colab).
Output: /kaggle/working/music_out/cand_<seed>.wav + runs_kaggle.jsonl
        -> download and run `make music-import DIR=<that folder>`

TODO before the first run: fill in setup() and generate_one() from the ACE-Step 1.5 README (install command,
how to pass caption, lyrics or the instrumental tag, duration, bpm, key and seed). Keep tempo and key in their
own fields, not in the caption. The timing and logging around it are already done.
"""
import datetime
import glob
import json
import os
import time
import uuid

OUT = "/kaggle/working/music_out" if os.path.isdir("/kaggle") else "/content/music_out"
job = json.load(open(glob.glob("/kaggle/input/**/jobs.json", recursive=True)[0] if os.path.isdir("/kaggle")
                     else "/content/jobs.json"))
os.makedirs(OUT, exist_ok=True)
log_path = f"{OUT}/runs_kaggle.jsonl"


def setup():
    """TODO: install ACE-Step 1.5 and download its weights (see its README)."""
    raise NotImplementedError("fill in setup() from the ACE-Step 1.5 README")


def generate_one(caption, lyrics, instrumental, duration_s, bpm, key, seed, dest):
    """TODO: generate one track and save it to dest (a .wav path)."""
    raise NotImplementedError("fill in generate_one() from the ACE-Step 1.5 README")


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
