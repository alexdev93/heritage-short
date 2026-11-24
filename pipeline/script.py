"""Stage: script — draft the storyboard from your story notes, and translate narration lines.

  draft      reads story/brief.md (your notes, in your words) and the schema, asks Gemini for a
             storyboard, validates it in code, feeds any errors back (up to 3 tries) and writes
             storyboard.draft.json. It never overwrites storyboard.json: you review and copy what you keep.
  translate  fills narration.text from narration.subtitle_en (--to-narration, default) or
             subtitle_en from narration.text (--to-english), for lines that are empty (or all with --force).
             One batched call. Have a native speaker check names and places afterwards.

Usage:
  python -m pipeline.script draft
  python -m pipeline.script translate [--to-english] [--force]
"""
from __future__ import annotations

import argparse
import json

from pipeline import common as C
from pipeline import config, providers
from pipeline.validate import check

BRIEF = C.ROOT / "story" / "brief.md"
DRAFT = C.ROOT / "storyboard.draft.json"


def _call(stage: str, model: str, prompt: str, json_mode: bool, params: dict) -> str:
    result = {}

    def attempt(i: int) -> None:
        with C.model_call(stage, "gemini", model, params, attempt=i) as rec:
            text, usage = providers.gemini_text(prompt, model, json_mode=json_mode)
            rec["usage"], rec["output"] = usage, f"{len(text)} chars"
            result["text"] = text

    C.with_retries(attempt)
    return result["text"]


def draft() -> None:
    if not BRIEF.exists():
        C.die("write story/brief.md first")
    schema = C.SCHEMA.read_text(encoding="utf-8")
    current = C.STORYBOARD.read_text(encoding="utf-8") if C.STORYBOARD.exists() else "{}"
    base = (
        "You are helping plan a 60-90 second short film. Write a storyboard as JSON that validates against "
        "the JSON Schema below. Use 8-12 shots of 5-9 seconds, one idea and one movement per shot, varied "
        "shot sizes, and a stated reason for every shot. Image prompts describe only what is in the frame "
        "(style and character descriptions are added automatically). Motion prompts describe only motion "
        "and camera, slow and gentle. Narration: short spoken sentences, about 2 words per second of shot. "
        "Keep narration.text empty if you cannot write the narration language well; fill subtitle_en. "
        "Use render.mode 'wan' for shots that need real motion and 'kenburns' for stills. Return only JSON.\n\n"
        f"JSON Schema:\n{schema}\n\nCurrent storyboard (keep its audience, intent, voice and style unless the notes "
        f"say otherwise):\n{current}\n\nStory notes:\n{BRIEF.read_text(encoding='utf-8')}"
    )
    prompt = base
    for attempt in range(1, 4):
        text = _call("script", config.MODELS["text"], prompt, True, {"task": "draft_storyboard", "try": attempt})
        try:
            sb = json.loads(text)
            errors, warnings, _ = check(sb)
        except json.JSONDecodeError as e:
            sb, errors, warnings = None, [f"not valid JSON: {e}"], []
        if sb is not None:
            DRAFT.write_text(json.dumps(sb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if not errors:
            for w in warnings:
                C.warn(w)
            print(f"  ✓ wrote {C.rel(DRAFT)} (try {attempt}). Review it, then copy what you keep into storyboard.json.")
            return
        C.warn(f"try {attempt}: {len(errors)} validation error(s); sending them back")
        prompt = base + "\n\nYour previous answer failed validation with these errors; fix them:\n" + "\n".join(errors[:30])
    C.die(f"no valid storyboard after 3 tries; the last attempt is in {C.rel(DRAFT)}")


def translate(to_english: bool, force: bool) -> None:
    sb = C.load_storyboard()
    src, dst = ("text", "subtitle_en") if to_english else ("subtitle_en", "text")
    lang = "English" if to_english else sb["language"]["narration"]
    todo = {s["id"]: s["narration"][src] for s in sb["shots"]
            if s["narration"][src].strip() and (force or not s["narration"][dst].strip())}
    if not todo:
        print("  ✓ nothing to translate")
        return
    prompt = (
        f"Translate each line into {lang} (language code if not English). This is narration for a short family "
        "film that will be spoken aloud: keep it natural, simple and warm, keep names and place names as they are, "
        "and keep each line about the same length. Return only a JSON object mapping each id to its translation.\n\n"
        + json.dumps(todo, ensure_ascii=False, indent=2)
    )
    if C.FAKE:
        out = {k: f"[{lang}] {v}" for k, v in todo.items()}
        _call("script", config.MODELS["text_lite"], prompt, True, {"task": "translate", "to": lang, "lines": len(todo)})
    else:
        out = json.loads(_call("script", config.MODELS["text_lite"], prompt, True,
                               {"task": "translate", "to": lang, "lines": len(todo)}))
    for s in sb["shots"]:
        if s["id"] in out:
            s["narration"][dst] = out[s["id"]].strip()
    C.save_storyboard(sb)
    print(f"  ✓ translated {len(out)} line(s) into {lang}; previous storyboard backed up in "
          f"{C.rel(C.OUT / 'storyboard_history')}. Ask a native speaker to check them.")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("draft")
    t = sub.add_parser("translate")
    t.add_argument("--to-english", action="store_true")
    t.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    with C.stage_timer(f"script-{args.cmd}"):
        if args.cmd == "draft":
            draft()
        else:
            translate(args.to_english, args.force)


if __name__ == "__main__":
    main()
