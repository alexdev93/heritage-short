"""Stage: keyframes — one still per shot (FLUX on Cloudflare Workers AI).

Reads:  storyboard.json (style, characters, shots[].image_prompt / shot_size / seed)
Writes: outputs/keyframes/<shot>-<hash>.png and outputs/keyframes/manifest.json

Every prompt = shot size + image_prompt + the fixed description of each character in the shot
+ the fixed style block, so the look stays consistent and only the shot-specific part varies.

Usage:
  python -m pipeline.keyframes                    build all keyframes (cached)
  python -m pipeline.keyframes --only s03         rebuild one shot if its inputs changed
  python -m pipeline.keyframes candidates s03 -n 3  explore seeds for one shot (no manifest change)
  python -m pipeline.keyframes refs grandmother -n 4  character reference-sheet candidates
"""
from __future__ import annotations

import argparse
import io

from pipeline import common as C
from pipeline import config, providers

SHOT_SIZE = {
    "extreme_wide": "extreme wide shot",
    "wide": "wide shot",
    "medium": "medium shot",
    "medium_close_up": "medium close-up",
    "close_up": "close-up",
    "extreme_close_up": "extreme close-up",
    "insert": "insert shot, detail",
}


def _clean(s: str) -> str:
    return s.strip().rstrip(".")


def build_prompt(sb: dict, shot: dict) -> str:
    chars = {c["id"]: c for c in sb["characters"]}
    parts = [SHOT_SIZE[shot["shot_size"]], shot["image_prompt"]]
    parts += [chars[c]["description"] for c in shot.get("characters", []) if c in chars]
    parts.append(sb["style"]["style_block"])
    return ". ".join(_clean(p) for p in parts if p and p.strip())


def reference_images(sb: dict, shot: dict) -> list[str]:
    chars = {c["id"]: c for c in sb["characters"]}
    refs = [chars[c].get("reference_image") for c in shot.get("characters", []) if c in chars]
    refs.append(sb["style"].get("reference_image"))
    return [r for r in refs if r]


def cache_key(sb: dict, shot: dict) -> str:
    model = config.MODELS["image"]
    key = {"prompt": build_prompt(sb, shot), "seed": shot["seed"], "model": model,
           "steps": config.CF_IMAGE_STEPS, "seed_sent": config.CF_IMAGE_SEND_SEED, "fake": C.FAKE}
    if "flux-2" in model:  # only models that actually use references depend on them
        key["refs"] = [C.file_sha(r) for r in reference_images(sb, shot)]
    return C.sha(key)


def _generate(path, prompt: str, seed: int, refs: list[str], *, stage: str, shot_id: str | None, key: str | None) -> None:
    from PIL import Image

    model = config.MODELS["image"]

    def attempt(i: int) -> None:
        params = {"prompt": prompt, "steps": config.CF_IMAGE_STEPS, "seed_sent": config.CF_IMAGE_SEND_SEED,
                  "references": refs}
        with C.model_call(stage, "cloudflare", model, params, shot_id=shot_id, seed=seed, cache_key=key, attempt=i) as rec:
            data, usage = providers.cf_image(prompt, seed, config.CF_IMAGE_STEPS, model, refs)
            Image.open(io.BytesIO(data)).convert("RGB").save(path, format="PNG")
            rec["usage"], rec["output"] = usage, C.rel(path)

    C.with_retries(attempt)


def build(only: set[str] | None = None, force: bool = False) -> None:
    sb = C.load_storyboard(require_consent=True)
    outdir = C.stage_dir("keyframes")
    manifest = C.Manifest(outdir / "manifest.json")
    made = cached = 0
    for shot in sb["shots"]:
        sid = shot["id"]
        if only and sid not in only:
            continue
        key = cache_key(sb, shot)
        path = outdir / f"{sid}-{key}.png"
        if path.exists() and not force:
            cached += 1
        else:
            _generate(path, build_prompt(sb, shot), shot["seed"], reference_images(sb, shot),
                      stage="keyframes", shot_id=sid, key=key)
            made += 1
            C.info(f"keyframe {sid}: generated {C.rel(path)}")
        manifest.set(sid, {"path": C.rel(path), "hash": key, "prompt": build_prompt(sb, shot)})
    manifest.save()
    print(f"  ✓ keyframes: {made} generated, {cached} cached")


def candidates(shot_id: str, n: int) -> None:
    sb = C.load_storyboard(require_consent=True)
    shot = next((s for s in sb["shots"] if s["id"] == shot_id), None)
    if not shot:
        C.die(f"no shot {shot_id}")
    if not config.CF_IMAGE_SEND_SEED and not C.FAKE:
        C.warn("CF_IMAGE_SEND_SEED=false: candidates will differ, but a seed cannot reproduce them later")
    outdir = C.stage_dir(f"keyframes/candidates/{shot_id}")
    prompt = build_prompt(sb, shot)
    for seed in range(shot["seed"], shot["seed"] + n):
        path = outdir / f"seed-{seed}.png"
        _generate(path, prompt, seed, reference_images(sb, shot), stage="keyframes-explore", shot_id=shot_id, key=None)
        C.info(C.rel(path))
    print(f"  ✓ {n} candidates. Put the seed you like in shots[{shot_id}].seed, then rerun keyframes.")


def refs(character_id: str, n: int) -> None:
    sb = C.load_storyboard(require_consent=True)
    char = next((c for c in sb["characters"] if c["id"] == character_id), None)
    if not char:
        C.die(f"no character {character_id}")
    outdir = C.stage_dir(f"keyframes/refs/{character_id}")
    prompt = (f"character reference sheet, the same person shown front view and side view, neutral expression, "
              f"plain light background. {_clean(char['description'])}. {_clean(sb['style']['style_block'])}")
    for seed in range(1000, 1000 + n):
        path = outdir / f"seed-{seed}.png"
        _generate(path, prompt, seed, [], stage="keyframes-refs", shot_id=None, key=None)
        C.info(C.rel(path))
    print(f"  ✓ {n} reference candidates. Set characters[{character_id}].reference_image to the one you approve.")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build")
    for p in (ap, b):
        p.add_argument("--only", help="comma-separated shot ids")
        p.add_argument("--force", action="store_true")
    c = sub.add_parser("candidates")
    c.add_argument("shot")
    c.add_argument("-n", type=int, default=3)
    r = sub.add_parser("refs")
    r.add_argument("character")
    r.add_argument("-n", type=int, default=4)
    args = ap.parse_args(argv)

    with C.stage_timer(f"keyframes-{args.cmd or 'build'}"):
        if args.cmd == "candidates":
            candidates(args.shot, args.n)
        elif args.cmd == "refs":
            refs(args.character, args.n)
        else:
            build(set(args.only.split(",")) if args.only else None, args.force)


if __name__ == "__main__":
    main()
