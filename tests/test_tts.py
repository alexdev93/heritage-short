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
