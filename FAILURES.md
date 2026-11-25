# Failures

Real blockers and what you did about them: quota, memory, queueing, consistency, language support, tools that
had moved. Write them as they happen — the details are gone by Thursday.

```
## F<n> — <what broke, in one line>
Date:
Symptom: exact error or what you saw/heard. Evidence: <runs.jsonl call id / log excerpt / file>
Cause (if known):
Tried: 1) … 2) …
Fix or workaround:
Cost: time lost, quota used.
```

<!-- entries below -->

## F1 — Pipeline crashed: ffprobe not found
Date: 2026-11-24
Symptom: `make fake-film` failed in the narration stage, after s01's wav was generated, with
FileNotFoundError: [Errno 2] No such file or directory: 'ffprobe' (common.media_duration).
Evidence: traceback from `make fake-film` (narration.py:59 → common.py:240).
Cause: FFmpeg was not installed on my machine; the pipeline assumed it was.
Tried: 1) installed ffmpeg with apt  2) added a startup check (see F1 fix)
Fix: `sudo apt install ffmpeg`, plus `pipeline/run.py` now checks for ffmpeg/ffprobe
before it runs any stage and says exactly what to install.
Cost: ~10 min.
