# Notes for the coding agent

This repo is a trainee's submission for the 10 Academy "Heritage Short" challenge: a multi-model pipeline that
turns `storyboard.json` into a 60–90 s film (9:16 and 16:9), narrated in the trainee's language with English
subtitles, an original score ducked under the voice, and an AI end card. Deadline: Thu 26 Nov, 23:59 EAT.

Graders read the repository as **text only** (code, logs, markdown) and then interview the trainee about it.
So: the trainee designs and decides; you write and explain code. Keep changes small and explain each one in a
sentence or two so the trainee can defend it in the interview.

## The contract
- `storyboard.json` is the single source of truth, validated by `schema/storyboard.schema.json` plus
  `pipeline/validate.py`. Ask before changing the schema; when you do, update the schema, `validate.py`,
  `tests/fixtures/storyboard.valid.json` and ARCHITECTURE.md together.
- Each stage (`pipeline/<stage>.py`) reads the storyboard and writes only `outputs/<stage>/` plus a
  `manifest.json` that records which file belongs to which shot.

## Rules
1. **Every model call goes through `common.model_call(...)`** (inside `common.with_retries`) so it is one line in
   `runs.jsonl`. Remote GPU runs write `runs_kaggle.jsonl`, merged on import. Never call a model outside it.
2. **Never bypass the cache.** Outputs are named `<shot>-<hash>.<ext>`; the hash covers every input that changes
   the output (prompt, seed, model, parameters, reference files). If you add an input, add it to the cache key
   and to the tests in `tests/test_pipeline.py`.
3. **No secrets in the repo.** Keys live in `.env` (gitignored); read them with `config.require(...)`.
4. **Consent gate:** keyframes, shot export and final assembly refuse to run while a `real_person` character has
   `consent.recorded: false`. Do not weaken this.
5. Keep `make test` green. Use `make fake-film` (PIPELINE_FAKE=1, writes to `outputs_fake/`) to test plumbing
   without spending quota.
6. When something breaks or an experiment finishes, draft an entry for FAILURES.md / EXPERIMENTS.md in the
   format at the top of those files and show it to the trainee. Do not write DESIGN.md user-test notes, the
   report, or the public post — those must be the trainee's own words.

## Commands
`make setup | smoke | test | validate | narration | keyframes | shots | music | radio-cut | film | draft | costs`
`make candidates SHOT=s03 N=3`, `make refs CHAR=main_person`, `make shots-export`, `make shots-import DIR=...`,
`make music-export`, `make music-import DIR=...`, `make keyframes ONLY=s03`.

## Known TODOs (good first tasks)
- Verify the Gemini text/TTS model IDs with `make smoke`; set them in `.env`.
- `providers.cf_image_flux2()`: FLUX.2 klein with reference images (character consistency). Check the
  Cloudflare Workers AI model page for the input format first.
- `kaggle/acestep_music.py`: fill in `generate_one()` from the ACE-Step 1.5 README.
- `kaggle/wan22_shots.py`: confirm the `generate.py` flags against the Wan 2.2 README; T4s have no bf16 and
  16 GB each, so expect to iterate (log it in FAILURES.md).
- Loudness: single-pass loudnorm lands about 1 LU under -14 LUFS; a two-pass loudnorm would hit it exactly.
