"""Stage: narration — one WAV per shot from Gemini TTS.

Reads:  storyboard.json (shots[].narration.text, voice, language)
Writes: outputs/narration/<shot>-<hash>.wav and outputs/narration/manifest.json

A line is regenerated only when its text, voice, style instruction or model changes.
Usage: python -m pipeline.narration [--only s01,s04] [--force]
"""
from __future__ import annotations

import argparse

from pipeline import common as C
from pipeline import config, providers


def cache_key(sb: dict, shot: dict) -> str:
    return C.sha({
        "text": shot["narration"]["text"].strip(),
        "voice": sb["voice"],
        "language": sb["language"]["narration"],
        "model": config.MODELS["tts"],
        "fake": C.FAKE,
    })


def run(only: set[str] | None = None, force: bool = False) -> None:
    sb = C.load_storyboard()
    outdir = C.stage_dir("narration")
    manifest = C.Manifest(outdir / "manifest.json")
    model = config.MODELS["tts"]
    made = cached = 0

    for shot in sb["shots"]:
        sid, text = shot["id"], shot["narration"]["text"].strip()
        if only and sid not in only:
            continue
        if not text:
            manifest.drop(sid)
            continue
        key = cache_key(sb, shot)
        path = outdir / f"{sid}-{key}.wav"

        if path.exists() and not force:
            cached += 1
        else:
            def attempt(i: int) -> None:
                params = {"voice": sb["voice"]["name"], "style_instruction": sb["voice"]["style_instruction"],
                          "language": sb["language"]["narration"], "chars": len(text)}
                with C.model_call("narration", "gemini", model, params, shot_id=sid, cache_key=key, attempt=i) as rec:
                    pcm, rate, usage = providers.gemini_tts(text, sb["voice"]["name"], sb["voice"]["style_instruction"], model)
                    providers.write_wav(path, pcm, rate)
                    rec["usage"], rec["output"] = usage, C.rel(path)

            C.with_retries(attempt)
            made += 1
            C.info(f"narration {sid}: generated {C.rel(path)}")

        dur = C.media_duration(path)
        manifest.set(sid, {"path": C.rel(path), "hash": key, "duration_s": round(dur, 3)})
        room = shot["duration_s"] - shot["narration"].get("offset_s", 0.3)
        if dur > room:
            C.warn(f"narration {sid} is {dur:.1f}s but the shot leaves {room:.1f}s — shorten the line or lengthen the shot")

    manifest.save()
    print(f"  ✓ narration: {made} generated, {cached} cached")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated shot ids")
    ap.add_argument("--force", action="store_true", help="ignore the cache")
    args = ap.parse_args(argv)
    with C.stage_timer("narration"):
        run(set(args.only.split(",")) if args.only else None, args.force)


if __name__ == "__main__":
    main()
