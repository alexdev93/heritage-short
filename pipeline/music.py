"""Stage: music — ACE-Step 1.5 score candidates (rendered on Kaggle/Colab), placeholder until one is chosen.

  export       writes outputs/music/export/jobs.json from storyboard.music (caption, bpm, key, length)
               -> run kaggle/acestep_music.py on it and download the candidates
  import DIR   copies candidate tracks into outputs/music/candidates/ and merges the remote call log
  build        resolves the track assembly uses: storyboard.music.chosen if set, else a placeholder pad
               (the placeholder is what the radio cut uses before any score exists)

Choosing a track is a human decision: listen to the candidates under the narration, set
music.chosen and music.chosen_reason in storyboard.json, and log the comparison in EXPERIMENTS.md.

Usage:
  python -m pipeline.music build
  python -m pipeline.music export [-n 3]
  python -m pipeline.music import path/to/candidates
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from pipeline import common as C
from pipeline import config
from pipeline.shots import merge_runs

AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def placeholder(total_s: float) -> Path:
    """A quiet, slowly breathing A-minor pad. Deterministic FFmpeg, not a model call."""
    path = C.stage_dir("music") / f"placeholder-{int(round(total_s))}s.wav"
    if not path.exists():
        expr = ("0.06*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*0.10*t))"
                "+0.05*sin(2*PI*261.63*t)*(0.6+0.4*sin(2*PI*0.13*t))"
                "+0.04*sin(2*PI*329.63*t)*(0.6+0.4*sin(2*PI*0.07*t))")
        C.ffmpeg("-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={total_s + 2:.2f}",
                 "-af", "lowpass=f=1200", "-ac", "2", str(path))
    return path


def build() -> None:
    sb = C.load_storyboard()
    manifest = C.Manifest(C.stage_dir("music") / "manifest.json")
    chosen = sb["music"].get("chosen")
    if chosen:
        manifest.data = {"path": chosen, "source": "chosen", "hash": C.file_sha(chosen),
                         "volume_db": sb["music"].get("volume_db", -8)}
        print(f"  ✓ music: using chosen track {chosen}")
    else:
        path = placeholder(C.total_length(sb))
        manifest.data = {"path": C.rel(path), "source": "placeholder", "hash": C.file_sha(C.rel(path)),
                         "volume_db": sb["music"].get("volume_db", -8)}
        C.warn("music.chosen is not set — using the placeholder pad")
        print(f"  ✓ music: placeholder {C.rel(path)}")
    manifest.save()


def export(n: int) -> None:
    sb = C.load_storyboard()
    m = sb["music"]
    exp = C.stage_dir("music/export")
    job = {"model": config.MODELS["music"], "caption": m["caption"], "bpm": m["bpm"], "key": m["key"],
           "duration_s": int(round(C.total_length(sb))) + 2, "instrumental": m["instrumental"],
           "lyrics": m.get("lyrics"), "seeds": list(range(100, 100 + n)), "cues": m["cues"]}
    job["job_key"] = C.sha(job)
    (exp / "jobs.json").write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  ✓ exported a {n}-candidate music job to {C.rel(exp / 'jobs.json')}")
    print("    Run kaggle/acestep_music.py with it (see kaggle/README.md), then `make music-import DIR=...`.")


def import_(src: str) -> None:
    src_dir = Path(src).expanduser().resolve()
    if not src_dir.exists():
        C.die(f"{src_dir} not found")
    dest = C.stage_dir("music/candidates")
    n = 0
    for f in src_dir.rglob("*"):
        if f.suffix.lower() in AUDIO_EXT:
            shutil.copy2(f, dest / f.name)
            n += 1
            C.info(C.rel(dest / f.name))
    merged = merge_runs(src_dir)
    print(f"  ✓ imported {n} candidate(s), merged {merged} call log line(s)")
    print("    Listen under the narration, then set music.chosen (and chosen_reason) in storyboard.json.")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("build")
    e = sub.add_parser("export")
    e.add_argument("-n", type=int, default=3)
    i = sub.add_parser("import")
    i.add_argument("dir")
    args = ap.parse_args(argv)
    with C.stage_timer(f"music-{args.cmd or 'build'}"):
        if args.cmd == "export":
            export(args.n)
        elif args.cmd == "import":
            import_(args.dir)
        else:
            build()


if __name__ == "__main__":
    main()
