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

## F9 — ACE-Step on Kaggle: uv installed to /usr/local/bin, script looked in ~/.local/bin
Date: 2026-11-26
Symptom: FileNotFoundError: [Errno 2] No such file or directory: '/root/.local/bin/uv' at
acestep_music.py:60 (`uv sync`), right after the ACE-Step-1.5 clone. No music generated.
Evidence: notebook byteforge46/heritage-music (interactive session), cell output traceback.
Cause: on Kaggle the job runs as root, and the uv installer put the binary in /usr/local/bin
(its own output said "installing to /usr/local/bin"); the script hardcoded UV = ~/.local/bin/uv.
Tried: 1) first run on GPU T4 x2 (T4 x1 and P100 were not offered in the accelerator list).
Fix or workaround: (pending) install uv with UV_INSTALL_DIR=$HOME/.local/bin so it lands where the
script looks; re-upload acestep_music.py as a new heritage-acestep-music dataset version and re-run.
Cost: ~3 min GPU quota; interactive session left idle on the T4 until stopped.

## F10 — Kaggle setup snags: accelerator choices and notebook name clash
Date: 2026-11-26
Symptom: 1) Accelerator list showed only None / GPU T4 x2 / TPU v5e-8, so the planned "GPU T4 x1"
(music) and the "GPU P100" fallback weren't available. 2) Renaming the Wan notebook to
"heritage-wan-shots" failed: "The requested title ... is already in use by a dataset."
Evidence: Kaggle notebook editor, Session options and title bar (byteforge46).
Cause: Kaggle's current accelerator offering; notebook and dataset slugs share a namespace per account.
Tried: 1) used GPU T4 x2 for both notebooks  2) renamed the notebook to heritage-wan-shots-nb.
Fix or workaround: both of the above. Wan Version 1 (Save & Run All) started running on T4 x2.
Cost: a few minutes; T4 x2 uses the same 30 h/week GPU quota.

## F11 — Wan 2.2 on a T4: decord import error, then CUDA out of memory at 1280*704
Date: 2026-11-26
Symptom: 1) Version 1: all 8 shots failed in ~10 s each with ModuleNotFoundError: No module named 'decord'
(wan/__init__.py imports speech2video unconditionally). 2) Version 3 (decord fix in): s01 failed after 497 s with
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 1.85 GiB ... total capacity of 14.56 GiB, 1.26 GiB free.
Evidence: heritage-wan-shots-nb logs, Versions 1 and 3 (runs_kaggle.jsonl not downloaded).
Cause: 1) S2V/Animate deps not installed for TI2V. 2) 1280*704 x 121 frames doesn't fit a 16 GB T4 even with
--offload_model True --t5_cpu --convert_model_dtype.
Tried: 1) made the speech2video/animate imports optional  2) Version 3 at 1280*704 (OOM).
Fix or workaround: WAN_SIZE=832*480 in .env (it's in the clip cache key, so jobs were re-exported with new keys);
wan22_shots.py adds 832*480 / 480*832 to Wan's SUPPORTED_SIZES for ti2v-5B, because generate.py only accepts 1280*704.
Version 4 (832*480, dataset v5): s01 also failed after 480 s with torch.OutOfMemoryError (tried to allocate
140 MiB, 22.8 MiB free). Cancelled v3 and v4 at ~21:25 EAT.
Outcome: no Wan clips for the deadline. All 8 shots render as Ken Burns over their keyframes (the built-in fallback);
film_9x16 / film_16x9 built at 21:28, 66 s, -14.1 LUFS. Next time: fewer frames (e.g. 49-81) or a 24 GB+ GPU.
Cost: ~6 min (v1) + ~36 min (v3) + ~16 min (v4) GPU on T4 x2.
