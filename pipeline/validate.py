"""Validate storyboard.json against the JSON Schema plus checks a schema cannot express.

Run before every stage (each stage calls it through common.load_storyboard).
Usage: python -m pipeline.validate
"""
from __future__ import annotations

import json
import sys

from pipeline import common as C

WORDS_PER_SECOND = 2.3  # rough guide from the brief; measure your own TTS output


def check(sb: dict) -> tuple[list[str], list[str], list[str]]:
    """Returns (errors, warnings, consent_issues)."""
    from jsonschema import Draft202012Validator

    schema = json.loads(C.SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = [f"schema: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
              for e in sorted(validator.iter_errors(sb), key=lambda e: list(map(str, e.absolute_path)))]
    if errors:
        return errors, [], []  # semantic checks assume a schema-valid document

    warnings: list[str] = []
    consent: list[str] = []

    ids = [s["id"] for s in sb["shots"]]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append(f"duplicate shot ids: {sorted(dupes)}")

    chars = {c["id"]: c for c in sb["characters"]}
    for c in sb["characters"]:
        if c["real_person"] and not (c.get("consent") or {}).get("recorded"):
            consent.append(f"consent gate: character '{c['id']}' is a real person with no recorded consent. "
                           "Record it in ETHICS.md and set consent.recorded = true before generating them.")
        ref = c.get("reference_image")
        if ref and not (C.ROOT / ref).exists():
            warnings.append(f"character '{c['id']}': reference_image {ref} does not exist")

    for shot in sb["shots"]:
        sid = shot["id"]
        for cid in shot.get("characters", []):
            if cid not in chars:
                errors.append(f"{sid}: unknown character '{cid}'")
        n = shot["narration"]
        if n["text"].strip() and not n["subtitle_en"].strip():
            errors.append(f"{sid}: narration has no English subtitle")
        words = len((n["subtitle_en"] or n["text"]).split())
        room = shot["duration_s"] - n.get("offset_s", 0.3)
        if words and words / WORDS_PER_SECOND > room + 0.5:
            warnings.append(f"{sid}: ~{words} words may not fit in {room:.1f}s — check after narration runs")

    total = C.total_length(sb)
    if not 60 <= total <= 90:
        warnings.append(f"total length is {total:.1f}s (shots + end card); the film must be 60–90 s")

    for cue in sb["music"]["cues"]:
        if cue["end_s"] <= cue["start_s"] or cue["end_s"] > total + 0.01:
            errors.append(f"music cue {cue} is outside 0–{total:.1f}s or ends before it starts")

    chosen = sb["music"].get("chosen")
    if chosen and not (C.ROOT / chosen).exists():
        errors.append(f"music.chosen {chosen} does not exist")

    if "ai" not in sb["end_card"]["text"].lower():
        warnings.append("end_card text should say the film was made with AI")

    todo = json.dumps(sb, ensure_ascii=False).count("TODO")
    if todo:
        warnings.append(f"{todo} TODO placeholder(s) left in storyboard.json")

    return errors, warnings, consent


def main(argv=None) -> None:
    sb = C.load_storyboard(validate=False)
    errors, warnings, consent = check(sb)
    for w in warnings + consent:
        C.warn(w)
        C._warned.add(w)  # later stages in the same run don't repeat it
    if errors:
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        raise SystemExit(1)
    _, base = C.timeline(sb)
    print(f"  ✓ storyboard valid: {len(sb['shots'])} shots, {C.total_length(sb):.1f}s total "
          f"({base:.1f}s shots + {sb['end_card']['duration_s']}s end card)")


if __name__ == "__main__":
    main(sys.argv[1:])
