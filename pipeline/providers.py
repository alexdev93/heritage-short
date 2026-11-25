"""Thin adapters around each hosted model. Stages call these; these never touch the cache.

Each function returns raw results plus a usage dict. Logging and retries happen in the caller
(through common.model_call / common.with_retries) so every attempt is one line in runs.jsonl.
"""
from __future__ import annotations

import base64
import functools
import io
import math
import os
import struct
import wave

from pipeline import common as C
from pipeline import config


# ---------- Gemini (text + TTS) ----------

@functools.cache  # one client for the whole run: a throwaway Client gets garbage-collected
def _gemini_client():  # mid-request and closes its connection ("client has been closed", F2)
    from google import genai  # imported lazily so fake mode needs no SDK

    # v1beta: this SDK defaults to v1, which has no TTS fields (speechConfig 400 / TTS model 404, F3).
    # timeout + attempts=1: fail within 2 min and let common.with_retries retry, so every attempt is
    # logged in runs.jsonl; the SDK's own silent retries had a radio cut hanging for 12+ min (F6).
    return genai.Client(api_key=config.require("GEMINI_API_KEY"),
                        http_options=genai.types.HttpOptions(
                            api_version="v1beta", timeout=GEMINI_TIMEOUT_MS,
                            retry_options=genai.types.HttpRetryOptions(attempts=1)))


GEMINI_TIMEOUT_MS = 120_000  # slowest TTS line so far took 55 s
_NETWORK_ERRORS = {"ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout", "TimeoutException",
                   "ConnectError", "ReadError", "RemoteProtocolError", "APITimeoutError", "APIConnectionError"}


def _wrap_gemini_error(e: Exception) -> Exception:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if code in C.RETRY_CODES:
        return C.RetryableError(f"Gemini HTTP {code}: {e}")
    if type(e).__name__ in _NETWORK_ERRORS:  # timeouts / dropped connections: worth another try
        return C.RetryableError(f"Gemini network: {type(e).__name__}: {e}")
    return e


def gemini_text(prompt: str, model: str, json_mode: bool = False) -> tuple[str, dict]:
    if C.FAKE:
        return "ok", {"tokens_in": len(prompt) // 4, "tokens_out": 1}
    from google.genai import types

    cfg = types.GenerateContentConfig(response_mime_type="application/json") if json_mode else None
    try:
        resp = _gemini_client().models.generate_content(model=model, contents=prompt, config=cfg)
    except Exception as e:  # noqa: BLE001
        raise _wrap_gemini_error(e) from e
    um = getattr(resp, "usage_metadata", None)
    usage = {
        "tokens_in": getattr(um, "prompt_token_count", None),
        "tokens_out": getattr(um, "candidates_token_count", None),
    }
    return resp.text or "", usage


def uses_interactions_api(model: str) -> bool:
    """Gemini 3.8 TTS models take the Interactions API; older TTS models take generateContent."""
    if config.TTS_API in ("interactions", "generate_content"):
        return config.TTS_API == "interactions"
    return "3.8" in model


def gemini_tts(text: str, voice: str, style_instruction: str, model: str) -> tuple[bytes, int, dict]:
    """Returns (16-bit mono PCM, sample_rate, usage)."""
    if C.FAKE:
        return _fake_speech(text), config.TTS_SAMPLE_RATE, {"chars": len(text)}
    if uses_interactions_api(model):
        return _gemini_tts_interactions(text, voice, style_instruction, model)
    return _gemini_tts_generate_content(text, voice, style_instruction, model)


def _gemini_tts_interactions(text: str, voice: str, style_instruction: str, model: str) -> tuple[bytes, int, dict]:
    """Gemini 3.8 TTS: the verbatim text, the style as a speech_metadata annotation, the voice in
    generation_config.speech_config (a list for one speaker). Unary replies are base64 WAV, 24 kHz mono 16-bit."""
    try:
        interaction = _gemini_client().interactions.create(
            model=model,
            input=[{
                "type": "user_input",
                "content": [{
                    "type": "text",
                    "text": text,
                    "annotations": [{"type": "speech_metadata", "style": style_instruction}],
                }],
            }],
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": voice}]},
        )
    except Exception as e:  # noqa: BLE001
        raise _wrap_gemini_error(e) from e
    audio = getattr(interaction, "output_audio", None)
    if audio is None or not getattr(audio, "data", None):
        raise RuntimeError(f"no audio in the Gemini reply: {str(interaction)[:300]}")
    raw = audio.data
    if isinstance(raw, str):
        raw = base64.b64decode(raw)
    elif not bytes(raw[:4]) == b"RIFF" and getattr(audio, "mime_type", "") != "audio/l16":
        try:
            raw = base64.b64decode(raw, validate=True)
        except Exception:  # noqa: BLE001 - already raw bytes
            pass
    if bytes(raw[:4]) == b"RIFF":
        pcm, rate = wav_to_pcm(bytes(raw))
    else:  # audio/l16: headerless PCM
        pcm, rate = bytes(raw), getattr(audio, "sample_rate", None) or config.TTS_SAMPLE_RATE
    usage = {"chars": len(text)}
    u = getattr(interaction, "usage", None)
    if u is not None and hasattr(u, "model_dump"):
        usage.update({k: v for k, v in u.model_dump().items() if isinstance(v, int)})
    return pcm, rate, usage


def wav_to_pcm(data: bytes) -> tuple[bytes, int]:
    with wave.open(io.BytesIO(data)) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise RuntimeError(f"expected 16-bit mono WAV, got {w.getnchannels()} channel(s), {8 * w.getsampwidth()}-bit")
        return w.readframes(w.getnframes()), w.getframerate()


def _gemini_tts_generate_content(text: str, voice: str, style_instruction: str, model: str) -> tuple[bytes, int, dict]:
    """Older TTS models (2.5, 3.1 preview): generateContent with speechConfig."""
    from google.genai import types

    prompt = f"{style_instruction.rstrip(':. ')}:\n{text}"
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))
        ),
    )
    try:
        resp = _gemini_client().models.generate_content(model=model, contents=prompt, config=cfg)
    except Exception as e:  # noqa: BLE001
        raise _wrap_gemini_error(e) from e
    part = resp.candidates[0].content.parts[0].inline_data
    data = part.data if isinstance(part.data, bytes) else base64.b64decode(part.data)
    rate = config.TTS_SAMPLE_RATE
    mime = getattr(part, "mime_type", "") or ""
    if "rate=" in mime:
        rate = int(mime.split("rate=")[1].split(";")[0])
    um = getattr(resp, "usage_metadata", None)
    usage = {"chars": len(text), "tokens_in": getattr(um, "prompt_token_count", None),
             "tokens_out": getattr(um, "candidates_token_count", None)}
    return data, rate, usage


def write_wav(path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


# ---------- Cloudflare Workers AI (keyframes) ----------

def cf_image(prompt: str, seed: int, steps: int, model: str, reference_images: list[str] | None = None) -> tuple[bytes, dict]:
    """Returns (image bytes, usage). FLUX.1 schnell: JSON in, base64 JPEG out."""
    if C.FAKE:
        return _fake_image(prompt, seed), {"images": 1}
    if "flux-2" in model:
        return cf_image_flux2(prompt, seed, steps, model, reference_images or [])
    import requests

    acct = config.require("CLOUDFLARE_ACCOUNT_ID")
    token = config.require("CLOUDFLARE_API_TOKEN")
    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
    body = {"prompt": prompt[:2048], "steps": steps}
    if config.CF_IMAGE_SEND_SEED:
        body["seed"] = seed
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=180)
    except requests.RequestException as e:
        raise C.RetryableError(f"network: {e}") from e
    if r.status_code in C.RETRY_CODES:
        raise C.RetryableError(f"Cloudflare HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400:
        raise RuntimeError(f"Cloudflare HTTP {r.status_code}: {r.text[:500]}")
    if r.headers.get("content-type", "").startswith("image/"):
        return r.content, {"images": 1}
    payload = r.json()
    image_b64 = (payload.get("result") or {}).get("image")
    if not image_b64:
        raise RuntimeError(f"no image in Cloudflare response: {str(payload)[:300]}")
    return base64.b64decode(image_b64), {"images": 1}


REF_MAX_SIDE = 511  # Workers AI: every FLUX.2 input image must be smaller than 512x512
REF_MAX_COUNT = 4   # input_image_0 … input_image_3


def reference_png(path: str) -> bytes:
    """Load a reference image, shrink it to fit inside 511x511 (keeping its shape), return PNG bytes.
    Crop references to head and shoulders BEFORE adding them: a full-body photo shrunk to 511 px
    leaves the face only a few dozen pixels wide."""
    from PIL import Image

    p = C.ROOT / path if not os.path.isabs(path) else path
    if not os.path.exists(p):
        raise FileNotFoundError(f"reference image {path} not found")
    img = Image.open(p).convert("RGB")
    img.thumbnail((REF_MAX_SIDE, REF_MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def cf_image_flux2(prompt, seed, steps, model, reference_images):
    """FLUX.2 (klein / dev) on Workers AI: multipart form data, even with no images.
    Reference images go in binary as input_image_0 … input_image_3 (each under 512x512); the prompt
    can name them as "image 0", "image 1". Reply: JSON with a base64 image in result.image."""
    import requests

    if len(reference_images) > REF_MAX_COUNT:
        raise ValueError(f"FLUX.2 takes at most {REF_MAX_COUNT} reference images, got {len(reference_images)}")
    acct = config.require("CLOUDFLARE_ACCOUNT_ID")
    token = config.require("CLOUDFLARE_API_TOKEN")
    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
    fields = {
        "prompt": (None, prompt),
        "steps": (None, str(steps)),
        "width": (None, str(config.CF_IMAGE_WIDTH)),
        "height": (None, str(config.CF_IMAGE_HEIGHT)),
    }
    if config.CF_IMAGE_SEND_SEED:
        fields["seed"] = (None, str(seed))
    for i, ref in enumerate(reference_images):
        fields[f"input_image_{i}"] = (f"reference_{i}.png", reference_png(ref), "image/png")
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, files=fields, timeout=180)
    except requests.RequestException as e:
        raise C.RetryableError(f"network: {e}") from e
    if r.status_code in C.RETRY_CODES:
        raise C.RetryableError(f"Cloudflare HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400:
        raise RuntimeError(f"Cloudflare HTTP {r.status_code}: {r.text[:500]}")
    if r.headers.get("content-type", "").startswith("image/"):
        return r.content, {"images": 1, "reference_images": len(reference_images)}
    payload = r.json()
    image_b64 = (payload.get("result") or {}).get("image")
    if not image_b64:
        raise RuntimeError(f"no image in Cloudflare response: {str(payload)[:300]}")
    return base64.b64decode(image_b64), {"images": 1, "reference_images": len(reference_images)}


# ---------- fake stand-ins (PIPELINE_FAKE=1) ----------

def _fake_speech(text: str) -> bytes:
    """A soft blip pattern as long as the line would take to say (~2.3 words/s)."""
    seconds = max(1.0, len(text.split()) / 2.3)
    rate = config.TTS_SAMPLE_RATE
    frames = []
    for i in range(int(seconds * rate)):
        t = i / rate
        env = 0.5 * (1 + math.sin(2 * math.pi * 3.0 * t))
        frames.append(int(9000 * env * math.sin(2 * math.pi * 190 * t)))
    return struct.pack(f"<{len(frames)}h", *frames)


def _fake_image(prompt: str, seed: int) -> bytes:
    from PIL import Image, ImageDraw

    h = int(C.sha([prompt, seed])[:6], 16)
    base = ((h >> 16) & 255, (h >> 8) & 255, h & 255)
    img = Image.new("RGB", (1024, 1024), base)
    draw = ImageDraw.Draw(img)
    for i in range(0, 1024, 64):  # grid so pan/zoom movement is visible
        draw.line([(i, 0), (i, 1024)], fill=(255, 255, 255), width=1)
        draw.line([(0, i), (1024, i)], fill=(255, 255, 255), width=1)
    draw.ellipse([412, 412, 612, 612], outline=(255, 255, 255), width=6)
    draw.text((40, 40), prompt[:80], fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
