"""Configuration: secrets and model IDs come from .env (never committed).

Model IDs change often. `make smoke` calls each one once and tells you if an ID is wrong.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (KEY=value lines). Real environment variables win."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def require(name: str) -> str:
    value = env(name)
    if not value:
        raise SystemExit(f"Missing {name}. Copy .env.example to .env and fill it in.")
    return value


MODELS = {
    "text": env("GEMINI_TEXT_MODEL", "gemini-3.8-flash"),
    "text_lite": env("GEMINI_LITE_MODEL", "gemini-3.8-flash-lite"),
    "tts": env("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts"),
    "image": env("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell"),
    "video": "Wan2.2-TI2V-5B",
    "music": "ACE-Step-1.5",
}

CF_IMAGE_STEPS = int(env("CF_IMAGE_STEPS", "4"))
CF_IMAGE_WIDTH = int(env("CF_IMAGE_WIDTH", "1024"))   # FLUX.2 only; FLUX.1 schnell picks its own size
CF_IMAGE_HEIGHT = int(env("CF_IMAGE_HEIGHT", "1024"))
# FLUX.1 schnell on Workers AI may not accept a seed; turn this on only if the model's schema lists one.
CF_IMAGE_SEND_SEED = env("CF_IMAGE_SEND_SEED", "false").lower() == "true"

WAN_SIZE = env("WAN_SIZE", "1280*704")  # 1280*704 is official for TI2V-5B but OOMs on a T4; .env uses 832*480
WAN_FPS = 24
WAN_MAX_FRAMES = 121  # about 5 s at 24 fps; frame counts must be 4n+1

TTS_SAMPLE_RATE = 24000  # Gemini TTS returns 16-bit mono PCM at 24 kHz
# auto: Gemini 3.8 TTS models use the Interactions API, older ones generateContent. Force with
# GEMINI_TTS_API=interactions or GEMINI_TTS_API=generate_content.
TTS_API = (env("GEMINI_TTS_API", "auto") or "auto").lower()
# Free tier: 3 TTS requests per minute, so space calls ~21 s apart. 0 turns pacing off (paid tier).
TTS_MIN_INTERVAL_S = float(env("GEMINI_TTS_MIN_INTERVAL_S", "21"))

# List-price equivalents for COSTS.md. Fill these in from each provider's pricing page
# (and note the date you checked). Leave None if there is no public price.
# unit: what one "usage" number in runs.jsonl counts.
LIST_PRICES_USD = {
    MODELS["text"]: {"unit": "1M_tokens", "usd": None},
    MODELS["text_lite"]: {"unit": "1M_tokens", "usd": None},
    MODELS["tts"]: {"unit": "1M_tokens", "usd": None},
    MODELS["image"]: {"unit": "image", "usd": None},
    MODELS["video"]: {"unit": "gpu_hour", "usd": None},  # e.g. a cloud T4/L4 hourly price
    MODELS["music"]: {"unit": "gpu_hour", "usd": None},
}
