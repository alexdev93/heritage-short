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

## F2 — Gemini calls failed instantly: "client has been closed"
Date: 2026-11-25
Symptom: `make smoke`: gemini text and tts both failed at once with
"RuntimeError: Cannot send a request, as the client has been closed."
Evidence: runs.jsonl calls 4dbd404c8a8b (text), 425f61dfd77b (tts).
Cause: providers.py made a new genai.Client on every call and kept no reference to it
(`_gemini_client().models.generate_content(...)`). google-genai 3.x closes the client's HTTP
connection when the Client is garbage-collected, which happened mid-request.
Tried: 1) checked the model ID: it was in models.list, so not the problem  2) cached one client.
Fix: `@functools.cache` on `_gemini_client()`: one client for the whole run.
Cost: ~10 min.

## F3 — Gemini TTS rejected: 400 "Unknown name speechConfig", then 404 model not found
Date: 2026-11-25
Symptom: narration (smoke and `make radio-cut`) failed with 400 INVALID_ARGUMENT
"Unknown name speechConfig at generation_config". After switching 3.8 TTS to the Interactions API:
404 "Model 'gemini-3.8-flash-tts' not found ... set the API version to 'v1beta'".
Evidence: runs.jsonl 1ca83264cfba (400), 15e2b897af6f (404); fallbacks 419bdb04ee2a,
361ce2e02455, c3b9c8dd6196; first success 0a69bf3865b2.
Cause: two problems stacked. 1) Gemini 3.8 TTS models only take the Interactions API, but the code
sent the older generateContent + speechConfig request. 2) google-genai 3.6 defaults to API
version v1, and TTS only exists in v1beta. The giveaway: even gemini-2.5-flash-preview-tts, which
does accept speechConfig, got the same 400, so the request format alone could not be the cause.
Tried: 1) Interactions API path for 3.8 TTS (tts-fix.patch): 400 became 404
2) fallback models 3.8-flash-lite-tts (404), 3.1-flash-tts-preview and 2.5-flash-preview-tts with
generateContent (both 400)  3) printed the client's api_version: v1.
Fix: client pinned to `api_version="v1beta"` in `_gemini_client()`, plus the Interactions path
for 3.8 TTS (GEMINI_TTS_API=auto|interactions|generate_content). Test: tests/test_tts.py.
Cost: ~1.5 h, TTS blocked the radio cut and the film.

## F4 — gemini-3.8-flash text: 503 after a ~20 min hang
Date: 2026-11-25
Symptom: smoke text check returned 503 UNAVAILABLE "Deadline expired" after ~20 min (13:53→14:13 UTC),
later "This model is currently experiencing high demand".
Evidence: runs.jsonl dfc250dff183, 8de2fafce245.
Cause: the newest flash model is overloaded; there is no client timeout, so the call just waited.
Tried: 1) gemini-3.5-flash instead: ok in ~3 s.
Fix or workaround: GEMINI_TEXT_MODEL=gemini-3.5-flash. Still open: a request timeout so one call can't hang a stage.
Cost: ~25 min waiting.
