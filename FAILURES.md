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

## F5 — The image model drew the jebena as a teapot and a kettle
Date: 2026-11-25
Symptom: in the example test (fictional story), the prompts asked for "a black clay jebena coffee pot".
s04 showed a European-style teapot on a modern stove; in s05 the grandmother pours from a metal kettle.
Same run: s07 asked for "a small child's hands" and got adult hands; s08 asked for evening and got daylight.
Evidence: outputs/keyframes/s04-f6e2b36e6ea4.png (runs.jsonl 59877717f788),
s05-192dab2410c3.png (89d6fcd2062c); contact sheet docs/example-keyframes.jpg.
Cause: FLUX.1 schnell doesn't know the word "jebena", so it falls back to the nearest common object.
Weak words ("small", "evening") lose to the style block's "golden morning light".
Tried: 1) not yet rerun — noted while reviewing the 8 keyframes.
Fix or workaround: describe objects by shape, not name ("a round-bottomed black clay pot with a long
narrow neck and a straw stopper"); state age and light strongly ("a seven-year-old girl's small hands",
"at night, lit by one warm lamp, dark window behind"). Applies to my real storyboard.
Cost: none yet (8 images, ~38 s); would cost a rerun per shot if it had reached the film.

## F6 — make radio-cut hung silently in narration for 12+ min
Date: 2026-11-25
Symptom: `make radio-cut` printed "▶ narration" and nothing else for 12 minutes; no new rows in runs.jsonl.
Evidence: process asleep (hrtimer_nanosleep) with a CLOSE-WAIT socket to Google; earlier the same
evening, FLUX.2 keyframe calls failed with NameResolutionError (runs.jsonl 715170808893, 9f2f670c3488).
Cause: the Gemini client had no timeout and the SDK retried internally, so our with_retries never
saw the error and nothing was logged. (The open item from F4.)
Tried: 1) checked the network: Google API reachable in ~1 s  2) read the SDK's retry options.
Fix: HttpOptions(timeout=120 s, retry_options attempts=1); timeouts/connection errors wrapped as
RetryableError so with_retries retries them visibly. Tests in tests/test_tts.py.
Cost: ~15 min.

## F7 — Gemini TTS free tier: 3 requests/minute and 10 requests/day
Date: 2026-11-25
Symptom: after cleaning outputs/ and regenerating, `make narration` failed with 429 "limit: 3 requests per
minute on Free Tier. Please retry in 43s"; the rerun hit "limit: 10 requests per day ... retry in 11h37m56s".
Evidence: runs.jsonl gemini-3.8-flash-tts rows with status error, 2026-11-25 ~20:20 UTC.
Cause: free-tier quotas; our retry backoff (2/4/8 s) was shorter than the 43 s the API asked for. Deleting the
cached narration also spent 6 of the day's 10 requests regenerating lines that already existed.
Tried: 1) pacing TTS calls 21 s apart  2) waiting as long as "retry in Ns" says  3) stopping at once when the
wait is hours (daily cap) instead of retrying.
Fix: config.TTS_MIN_INTERVAL_S (GEMINI_TTS_MIN_INTERVAL_S, default 21); common.retry_after_s() + with_retries
honours the hint and fails fast with "quota exhausted" over 5 min. Fixed s03/s07 timing by lengthening the
shots (8.0 s) instead of re-recording, which needs no TTS call. Tests in tests/test_tts.py.
Lesson: never delete outputs/narration — narration is the scarcest quota (10 lines/day).
Cost: today's TTS quota; no more narration until ~11:40 tomorrow.

## F8 — Wan 2.2 on Kaggle: 12 h queue, 34 GB weights, removed CLI, no flash-attn on T4
Date: 2026-11-26
Symptom: Version #1 of the Kaggle notebook (GPU T4 x2) sat in the free GPU queue for 12 h without starting;
a live session was at queue position 682. Getting the script ready to run surfaced three more problems:
1) Wan2.2-TI2V-5B weights are 34.2 GB but /kaggle/working is limited to 20 GB.
2) `huggingface-cli download` no longer exists (removed in huggingface_hub 1.0).
3) Wan2.2's model.py imports flash_attention, which asserts flash-attn is installed; flash-attn can't run on a T4.
Evidence: notebook alemayehumekonen93/notebook076d97859d, Version #1 (cancelled, no output, 0 GPU h used).
Cause: free-tier GPU demand; script written against older huggingface_hub and for Ampere+ GPUs.
Tried: 1) cancelled Version #1, queued Version #2 (Save & Run All)  2) patched kaggle/wan22_shots.py.
Fix: REPO/CKPT under /kaggle/temp (outside the 20 GB limit); weights via huggingface_hub.snapshot_download;
model.py patched to `from .attention import attention as flash_attention` (torch SDPA fallback).
Still open: Version #2 queued; risk of GPU out-of-memory at 1280*704, 121 frames on a 16 GB T4.
Fallback: s05 renders as Ken Burns (pull_out) if no clip comes back.
Cost: ~12 h waiting (no GPU quota used).
