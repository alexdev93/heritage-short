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
