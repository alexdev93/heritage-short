"""Thin adapters around each hosted model. Stages call these; these never touch the cache.

Each function returns raw results plus a usage dict. Logging and retries happen in the caller
(through common.model_call / common.with_retries) so every attempt is one line in runs.jsonl.
"""
from __future__ import annotations

import base64
import functools
import io
import math
import struct
import wave

from pipeline import common as C
from pipeline import config


# ---------- Gemini (text + TTS) ----------

@functools.cache  # one client for the whole run: a throwaway Client gets garbage-collected
def _gemini_client():  # mid-request and closes its connection ("client has been closed", F2)
    from google import genai  # imported lazily so fake mode needs no SDK

    return genai.Client(api_key=config.require("GEMINI_API_KEY"))


def _wrap_gemini_error(e: Exception) -> Exception:
    code = getattr(e, "code", None)
    if code in C.RETRY_CODES:
        return C.RetryableError(f"Gemini HTTP {code}: {e}")
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


def gemini_tts(text: str, voice: str, style_instruction: str, model: str) -> tuple[bytes, int, dict]:
    """Returns (16-bit mono PCM, sample_rate, usage)."""
    if C.FAKE:
        return _fake_speech(text), config.TTS_SAMPLE_RATE, {"chars": len(text)}
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


def cf_image_flux2(prompt, seed, steps, model, reference_images):
    """TODO: FLUX.2 klein with reference images (character sheet conditioning).

    Check the model page under https://developers.cloudflare.com/workers-ai/models/ for the
    exact input format (FLUX.2 models take multipart form data with reference images).
    Return (image_bytes, {"images": 1}) like cf_image(), and raise C.RetryableError on 429/5xx.
    """
    raise NotImplementedError("FLUX.2 adapter not written yet — see cf_image_flux2() docstring.")


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
