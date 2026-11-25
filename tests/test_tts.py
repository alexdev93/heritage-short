"""Gemini 3.8 TTS goes through the Interactions API (FAILURES F3). No network: the client is faked."""
import base64
import io
import wave
from types import SimpleNamespace

from pipeline import providers


def _wav_bytes(seconds=0.5, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(seconds * rate))
    return buf.getvalue()


class _FakeInteractions:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def create(self, **body):
        self.calls.append(body)
        return self.reply


def _fake_client(monkeypatch, reply):
    fake = _FakeInteractions(reply)
    monkeypatch.setattr(providers, "_gemini_client", lambda: SimpleNamespace(interactions=fake))
    monkeypatch.setattr(providers.C, "FAKE", False)
    monkeypatch.setattr(providers.config, "TTS_MIN_INTERVAL_S", 0.0)  # no real waiting in tests
    return fake


def test_38_models_route_to_interactions(monkeypatch):
    monkeypatch.setattr(providers.config, "TTS_API", "auto")
    assert providers.uses_interactions_api("gemini-3.8-flash-tts")
    assert not providers.uses_interactions_api("gemini-2.5-flash-preview-tts")


def test_interactions_request_shape_and_wav_reply(monkeypatch):
    monkeypatch.setattr(providers.config, "TTS_API", "auto")
    reply = SimpleNamespace(output_audio=SimpleNamespace(
        data=base64.b64encode(_wav_bytes()).decode(), mime_type="audio/wav"), usage=None)
    fake = _fake_client(monkeypatch, reply)
    pcm, rate, usage = providers.gemini_tts("ሰላም", "Kore", "calm and warm", "gemini-3.8-flash-tts")
    body = fake.calls[0]
    assert body["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
    assert body["response_format"] == {"type": "audio"}
    part = body["input"][0]["content"][0]
    assert part["text"] == "ሰላም"
    assert part["annotations"] == [{"type": "speech_metadata", "style": "calm and warm"}]
    assert rate == 24000 and len(pcm) == 2 * 12000 and usage["chars"] == 3


def test_interactions_raw_pcm_reply(monkeypatch):
    monkeypatch.setattr(providers.config, "TTS_API", "auto")
    reply = SimpleNamespace(output_audio=SimpleNamespace(data=b"\x00\x01" * 100, mime_type="audio/l16",
                                                         sample_rate=24000), usage=None)
    _fake_client(monkeypatch, reply)
    pcm, rate, _ = providers.gemini_tts("hi", "Kore", "calm", "gemini-3.8-flash-tts")
    assert rate == 24000 and len(pcm) == 200


def test_client_uses_v1beta(monkeypatch):
    """TTS fields only exist in v1beta; the SDK default (v1) rejects them (FAILURES F3)."""
    monkeypatch.setattr(providers.config, "require", lambda name: "test-key")
    providers._gemini_client.cache_clear()
    try:
        assert providers._gemini_client()._api_client._http_options.api_version == "v1beta"
    finally:
        providers._gemini_client.cache_clear()


def test_client_times_out_and_leaves_retries_to_the_pipeline(monkeypatch):
    """The SDK's own silent retries hung a radio cut for 12+ min (FAILURES F6)."""
    monkeypatch.setattr(providers.config, "require", lambda name: "test-key")
    providers._gemini_client.cache_clear()
    try:
        opts = providers._gemini_client()._api_client._http_options
        assert opts.timeout == providers.GEMINI_TIMEOUT_MS
        assert opts.retry_options.attempts == 1
    finally:
        providers._gemini_client.cache_clear()


def test_network_errors_become_retryable():
    class ReadTimeout(Exception):
        pass
    assert isinstance(providers._wrap_gemini_error(ReadTimeout("slow")), providers.C.RetryableError)
    assert not isinstance(providers._wrap_gemini_error(ValueError("bad")), providers.C.RetryableError)


def test_retry_waits_as_long_as_the_rate_limit_says(monkeypatch):
    """429 'Please retry in 43s' must wait ~43 s, not the 2-8 s backoff (FAILURES F7)."""
    slept, calls = [], []
    monkeypatch.setattr(providers.C.time, "sleep", slept.append)

    def fn(i):
        calls.append(i)
        if i == 1:
            raise providers.C.RetryableError("Gemini HTTP 429: ... Please retry in 43s or upgrade")
        return "ok"
    assert providers.C.with_retries(fn) == "ok"
    assert calls == [1, 2] and slept[0] >= 44


def test_tts_calls_are_paced(monkeypatch):
    slept = []
    monkeypatch.setattr(providers.time, "sleep", slept.append)
    monkeypatch.setattr(providers.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(providers.config, "TTS_MIN_INTERVAL_S", 21.0)
    monkeypatch.setattr(providers, "_last_tts_call", [95.0])
    providers._pace_tts()
    assert slept == [16.0]


def test_daily_quota_stops_at_once_instead_of_retrying(monkeypatch):
    """'retry in 11h37m56s' is a daily cap: fail on the first attempt with a clear message (F7)."""
    import pytest
    calls = []
    monkeypatch.setattr(providers.C.time, "sleep", lambda s: None)

    def fn(i):
        calls.append(i)
        raise providers.C.RetryableError("429 ... 10 requests per day ... Please retry in 11h37m56s or upgrade")
    with pytest.raises(RuntimeError, match="quota exhausted"):
        providers.C.with_retries(fn)
    assert calls == [1]
    assert providers.C.retry_after_s("Please retry in 11h37m56s") == 11 * 3600 + 37 * 60 + 56
