"""Stage: moving shots — Wan 2.2 image-to-video clips (rendered on Kaggle), Ken Burns fallback.

Wan 2.2 needs a GPU, so this stage is split in three:
  export  writes outputs/shots/export/ (jobs.json + keyframes) for shots whose clip is missing
          -> upload that folder as a Kaggle dataset and run kaggle/wan22_shots.py on it
  import  copies the clips (<shot>-<clip_key>.mp4) and the Kaggle call log back into the repo
  build   decides, per shot, which source assembly uses and writes outputs/shots/manifest.json:
          the Wan clip if one exists for the current inputs, otherwise a Ken Burns move over the keyframe

A clip is tied to a hash of its keyframe, motion prompt, seed and Wan settings, so changing one
shot invalidates only that shot's clip.

Usage:
  python -m pipeline.shots build
  python -m pipeline.shots export
  python -m pipeline.shots import path/to/kaggle_output
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from pathlib import Path

from pipeline import common as C
from pipeline import config

CLIP_RE = re.compile(r"^(s\d{2})-([0-9a-f]{12})\.mp4$")


def frame_num(duration_s: float) -> int:
    frames = min(config.WAN_MAX_FRAMES, math.ceil(duration_s * config.WAN_FPS))
    return 4 * math.ceil((frames - 1) / 4) + 1  # Wan needs 4n+1 frames


def clip_key(shot: dict, keyframe_hash: str) -> str:
    return C.sha({"keyframe": keyframe_hash, "motion": shot["motion_prompt"].strip(), "seed": shot["seed"],
                  "size": config.WAN_SIZE, "frames": frame_num(shot["duration_s"]),
                  "model": config.MODELS["video"], "fake": C.FAKE})


def _keyframes(sb: dict) -> dict:
    kf = C.Manifest(C.OUT / "keyframes" / "manifest.json")
    missing = [s["id"] for s in sb["shots"] if not kf.get(s["id"])]
    if missing:
        C.die(f"no keyframes for {missing}; run keyframes first")
    return kf.data


def build() -> None:
    sb = C.load_storyboard()
    kf = _keyframes(sb)
    outdir = C.stage_dir("shots")
    manifest = C.Manifest(outdir / "manifest.json")
    manifest.data = {}
    counts = {"clip": 0, "kenburns": 0, "fallback": 0}
    for shot in sb["shots"]:
        sid, render = shot["id"], shot["render"]
        frame = kf[sid]
        entry = {"keyframe": frame["path"], "kenburns": render.get("kenburns", "push_in"),
                 "crop_focus_x": render.get("crop_focus_x", 0.5), "trim_start_s": render.get("trim_start_s", 0.0)}
        if render["mode"] == "wan":
            key = clip_key(shot, frame["hash"])
            clip = outdir / f"{sid}-{key}.mp4"
            if clip.exists():
                entry.update(source="clip", path=C.rel(clip), hash=key)
                counts["clip"] += 1
            else:
                entry.update(source="kenburns", path=frame["path"], hash=frame["hash"], fallback=True)
                counts["fallback"] += 1
                C.warn(f"{sid}: no Wan clip for the current inputs (key {key}); using Ken Burns. "
                       "Run `make shots-export`, render on Kaggle, then `make shots-import DIR=...`.")
        else:
            entry.update(source="kenburns", path=frame["path"], hash=frame["hash"])
            counts["kenburns"] += 1
        manifest.set(sid, entry)
    manifest.save()
    print(f"  ✓ shots: {counts['clip']} Wan clips, {counts['kenburns']} Ken Burns, {counts['fallback']} fallbacks")


def export() -> None:
    sb = C.load_storyboard(require_consent=True)
    kf = _keyframes(sb)
    outdir = C.stage_dir("shots")
    exp = outdir / "export"
    if exp.exists():
        shutil.rmtree(exp)
    (exp / "keyframes").mkdir(parents=True)
    jobs = []
    for shot in sb["shots"]:
        if shot["render"]["mode"] != "wan":
            continue
        sid, frame = shot["id"], kf[shot["id"]]
        key = clip_key(shot, frame["hash"])
        if (outdir / f"{sid}-{key}.mp4").exists():
            continue
        img = Path(frame["path"]).name
        shutil.copy2(C.ROOT / frame["path"], exp / "keyframes" / img)
        jobs.append({"shot_id": sid, "clip_key": key, "image": f"keyframes/{img}", "prompt": shot["motion_prompt"].strip(),
                     "seed": shot["seed"], "size": config.WAN_SIZE, "frame_num": frame_num(shot["duration_s"]),
                     "model": config.MODELS["video"]})
    (exp / "jobs.json").write_text(json.dumps(jobs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not jobs:
        print("  ✓ every Wan shot already has a clip for its current inputs; nothing to export")
        return
    print(f"  ✓ exported {len(jobs)} job(s) to {C.rel(exp)}")
    print("    Upload that folder as a Kaggle dataset and run kaggle/wan22_shots.py (see kaggle/README.md).")


def import_(src: str) -> None:
    src_dir = Path(src).expanduser().resolve()
    if not src_dir.exists():
        C.die(f"{src_dir} not found")
    outdir = C.stage_dir("shots")
    n = 0
    for clip in src_dir.rglob("*.mp4"):
        if CLIP_RE.match(clip.name):
            shutil.copy2(clip, outdir / clip.name)
            n += 1
        else:
            C.warn(f"skipping {clip.name}: name is not <shot>-<clip_key>.mp4")
    merged = merge_runs(src_dir)
    print(f"  ✓ imported {n} clip(s), merged {merged} Kaggle call log line(s) into {C.rel(C.RUNS)}")
    print("    Now run `make shots` (or `make film`) to use them.")


def merge_runs(src_dir: Path) -> int:
    """Append remote call logs (runs_kaggle.jsonl) to runs.jsonl, skipping lines already present."""
    seen = set()
    if C.RUNS.exists():
        for line in C.RUNS.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line).get("call_id"))
            except json.JSONDecodeError:
                pass
    added = 0
    for log in src_dir.rglob("runs_kaggle*.jsonl"):
        for line in log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("call_id") in seen:
                continue
            C.append_jsonl(C.RUNS, rec)
            seen.add(rec.get("call_id"))
            added += 1
    return added


def fake_clips() -> None:
    """PIPELINE_FAKE only: pretend to be Kaggle so the export/import path can be tested."""
    if not C.FAKE:
        C.die("fake-clips only runs with PIPELINE_FAKE=1")
    exp = C.OUT / "shots" / "export"
    jobs = json.loads((exp / "jobs.json").read_text(encoding="utf-8"))
    out = exp / "kaggle_output"
    out.mkdir(exist_ok=True)
    w, h = (int(x) for x in config.WAN_SIZE.split("*"))
    for job in jobs:
        dest = out / f"{job['shot_id']}-{job['clip_key']}.mp4"
        frames = job["frame_num"]
        with C.model_call("shots", "kaggle", job["model"], {"size": job["size"], "frame_num": frames},
                          shot_id=job["shot_id"], seed=job["seed"], cache_key=job["clip_key"]) as rec:
            C.ffmpeg("-i", str(exp / job["image"]), "-vf",
                     f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
                     f"zoompan=z='1+0.2*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps=24,"
                     "hue=s=0", "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest))
            rec["output"] = str(dest.name)
    print(f"  ✓ fake-rendered {len(jobs)} clip(s) into {C.rel(out)}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("build")
    sub.add_parser("export")
    imp = sub.add_parser("import")
    imp.add_argument("dir")
    sub.add_parser("fake-clips")
    args = ap.parse_args(argv)
    with C.stage_timer(f"shots-{args.cmd or 'build'}"):
        if args.cmd == "export":
            export()
        elif args.cmd == "import":
            import_(args.dir)
        elif args.cmd == "fake-clips":
            fake_clips()
        else:
            build()


if __name__ == "__main__":
    main()
