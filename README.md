# TODO: Film title

A 60–90 second heritage short, narrated in TODO-language with English subtitles and an original score, made by a
code pipeline that turns one written storyboard into keyframes, moving shots, music, narration and a finished edit.

**Watch:** TODO vertical link · TODO horizontal link · TODO post link

## Run it

```bash
make setup          # .venv + dependencies, creates .env from .env.example
# fill in .env (Gemini key, Cloudflare account ID + token)
make smoke          # calls each provider once; fix anything red first
make film           # the whole pipeline -> outputs/final/film_9x16.mp4 and film_16x9.mp4
```

No `make`? `python -m pipeline.run film` does the same.

Requirements: Python 3.10+, FFmpeg built with libass (for burned-in subtitles). Wan 2.2 and ACE-Step run on a
free Kaggle GPU — see [kaggle/README.md](kaggle/README.md). Without them the pipeline still finishes: shots fall back
to a slow pan/zoom over the keyframe and the score to a placeholder pad.

## How it works

`storyboard.json` is the contract between every stage. Each stage reads it, writes only its own outputs, and is
cached by a hash of its inputs, so changing one shot regenerates only that shot.

| Stage | Command | Model | Runs on | Output |
|---|---|---|---|---|
| script | `make draft-storyboard`, `make translate` | Gemini Flash / Flash-Lite | Gemini API | `storyboard.draft.json`, narration lines |
| narration | `make narration` | Gemini TTS | Gemini API | `outputs/narration/` |
| keyframes | `make keyframes` | FLUX (Workers AI) | Cloudflare | `outputs/keyframes/` |
| shots | `make shots-export` → Kaggle → `make shots-import` | Wan 2.2 TI2V-5B | Kaggle T4 | `outputs/shots/` |
| music | `make music-export` → Kaggle → `make music-import` | ACE-Step 1.5 | Kaggle/Colab | `outputs/music/` |
| assemble | `make film` / `make radio-cut` | FFmpeg (no AI) | your machine | `outputs/final/`, `outputs/radio_cut.mp4` |

Every model call is one line in `runs.jsonl` (model, parameters, seed, latency, usage). `make costs` turns it
into the tables in [COSTS.md](COSTS.md). Details: [ARCHITECTURE.md](ARCHITECTURE.md).

## Regenerate one shot

```bash
# edit shots[2].image_prompt (or one narration line) in storyboard.json, then
make film
# -> "keyframes: 1 generated, 7 cached" and one new line in runs.jsonl
```

## What it costs

TODO: total measured latency, GPU minutes and list-price equivalent from COSTS.md. Actual spend: $0 (free tiers).

## Repository

```
storyboard.json   the contract              schema/        JSON Schema, validated before every stage
pipeline/         one script per stage      kaggle/        GPU scripts for Wan 2.2 and ACE-Step
runs.jsonl        one line per model call   outputs/       generated media, kept for inspection
DESIGN.md  ARCHITECTURE.md  EXPERIMENTS.md  FAILURES.md  COSTS.md  ETHICS.md
```

Test the plumbing without spending quota: `make fake-film` (stand-in models, writes to `outputs_fake/`). `make test`
runs the schema and cache tests.
