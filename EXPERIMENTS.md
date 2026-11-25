# Experiments

About ten is a good target. One entry per question you tested. Point to evidence: `runs.jsonl` call ids,
output file names, user-test notes. Keep entries short and honest, including the ones that didn't work.

```
## E<n> — <question in one line>
Date:
Hypothesis: If I <change>, then <expected result>, because <reason>.
Change: what exactly changed (storyboard field, model, parameter, seed). Commit: <hash>
Result: what happened, with numbers where possible (latency, pass/fail, preference count). Evidence: <call ids / files>
Decision: keep / revert / try next.
```

Ideas worth testing: reference sheet vs no reference for character consistency · fixed vs varied seed ·
Wan at 1280*704 cropped to 9:16 vs rendering 704*1280 · Ken Burns vs Wan for a given shot · TTS style
instruction variants · ACE-Step caption detail (short vs long) · ducking settings · narration speed vs shot length ·
one practice from the brief vs your own instinct (you'll need one of each for the report).

<!-- entries below -->

## E1 — How long does one keyframe take on Cloudflare FLUX.1 schnell?
Date: 2026-11-25
Hypothesis: If I generate 8 keyframes at 1024×1024 with 4 steps, each takes under 10 s, because schnell is a
4-step distilled model.
Change: none — measured the example test's `make keyframes` (8 shots, @cf/black-forest-labs/flux-1-schnell, 4 steps).
Result: 2.9–9.5 s per image, mean 4.7 s; whole stage 38 s. Smoke-test images took 3.7, 4.8 and 17.7 s, so
there is occasional queueing. Evidence: runs.jsonl 83eb755fd7a7 … fc7d19d27c0f; outputs/stage_times.jsonl.
Decision: keep. Keyframes are cheap enough to run `make candidates` (3 seeds) on every weak shot.

## E2 — Does the cache really skip work on a rerun?
Date: 2026-11-25
Hypothesis: If I rerun the pipeline without changing storyboard.json, no model is called, because every
output is named <shot>-<hash> and the hash covers all its inputs.
Change: reran `make keyframes`, then `make film` twice, with no storyboard changes.
Result: keyframes "0 generated, 8 cached"; narration "0 generated, 8 cached"; no new rows in runs.jsonl.
Assembly: 238 s the first time, 100 s on the rerun (shot segments cached; only the final mix and both
encodes redone). Evidence: outputs/stage_times.jsonl; runs.jsonl has no calls after 14:32 UTC for that run.
Decision: keep. Next: change one narration line → expect "1 generated, 7 cached" (walkthrough demo).

## E3 — Does one style block keep 8 frames consistent, and does the character stay the same?
Date: 2026-11-25
Hypothesis: If every image prompt starts with the same style_block and the character's fixed description,
the style and the grandmother look the same in every shot, because FLUX follows the text closely.
Change: none — reviewed the example's 8 keyframes (no reference image; FLUX.1 schnell, text only).
Result: style holds in all 8 (warm gouache, same palette). The grandmother's clothes hold in s02, s05,
s06 (white netela, green border), but her face drifts: thinner in s02, rounder in s05. Signature-like
scribbles appear in corners of s01, s03, s06 despite "no text or letters".
Evidence: docs/example-keyframes.jpg; outputs/keyframes/s02-297dabf5d7eb.png, s05-192dab2410c3.png.
Decision: text alone keeps clothes, not faces. Try the FLUX.2 reference adapter (max 45 min); otherwise keep
faces small or turned away, and pick clean seeds with `make candidates`.

## E4 — How long does final assembly take on my laptop?
Date: 2026-11-25
Hypothesis: If I assemble a 64 s film in both 9:16 and 16:9, it takes about a minute, because it is
only Ken Burns moves on 8 stills plus an audio mix.
Change: none — timed `make fake-film` and the real `make film`.
Result: fake film 221 s end to end; real film assembly 238 s for both aspects (100 s on a rerun with cached
segments); radio cut 22 s. About 3× slower than the reference machine. Evidence: outputs/stage_times.jsonl.
Decision: use `make draft` (half resolution) while iterating; full `make film` only for tester versions and
the final. Budget ~4 min per full render in the plan.
