"""One command for the whole pipeline (what `make film` calls).

  python -m pipeline.run film     validate -> narration -> keyframes -> shots -> music -> assemble (both aspects)
  python -m pipeline.run draft    the same at half resolution, faster
  python -m pipeline.run radio    validate -> narration -> music -> radio cut (no pictures)

Every stage is cached, so a rerun only regenerates what changed in storyboard.json.
"""
from __future__ import annotations

import shutil
import sys
import time

from pipeline import assemble, keyframes, music, narration, shots, validate

PLANS = {
    "film": [("validate", validate.main, []), ("narration", narration.main, []), ("keyframes", keyframes.main, []),
             ("shots", shots.main, ["build"]), ("music", music.main, ["build"]), ("assemble", assemble.main, [])],
    "draft": [("validate", validate.main, []), ("narration", narration.main, []), ("keyframes", keyframes.main, []),
              ("shots", shots.main, ["build"]), ("music", music.main, ["build"]), ("assemble", assemble.main, ["--draft"])],
    "radio": [("validate", validate.main, []), ("narration", narration.main, []), ("music", music.main, ["build"]),
              ("assemble", assemble.main, ["--radio"])],
}


def check_tools() -> None:
    """Fail fast if FFmpeg is missing, instead of crashing halfway through narration (F1)."""
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise SystemExit("FFmpeg is not installed: run `sudo apt install ffmpeg`")


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    plan = argv[0] if argv else "film"
    if plan not in PLANS:
        raise SystemExit(f"usage: python -m pipeline.run [{'|'.join(PLANS)}]")
    check_tools()
    t0 = time.perf_counter()
    for name, fn, args in PLANS[plan]:
        print(f"\n▶ {name}", flush=True)
        fn(args)
    print(f"\n✓ {plan} done in {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    main()
