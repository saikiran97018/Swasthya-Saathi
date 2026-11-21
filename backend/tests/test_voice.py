"""Voice endpoints and the Bhashini client (against a fake Bhashini)."""
import asyncio

import pytest

from app.core.config import Settings
from app.core.errors import ServiceUnavailable, UpstreamError
from app.services.bhashini_service import BhashiniService
from tests.fakes import FakeBhashini, make_wav

P = "/api/v1"


def _upload(client, auth, wav, language="te", name="speech.wav"):
    return client.post(f"{P}/voice/transcribe", files={"audio": (name, wav, "audio/wav")}, data={"language": language}, headers=auth)


def test_transcribe_returns_text_in_requested_language(client, auth, bhashini):
    bhashini.transcript = "నాకు రేషన్ కార్డ్ కావాలి"
    r = _upload(client, auth, make_wav(1.5))
    assert r.status_code == 200, r.text
    assert r.json() == {"text": "నాకు రేషన్ కార్డ్ కావాలి", "language": "te", "duration_seconds": 1.5}
    call = bhashini.compute_calls[0]["pipelineTasks"][0]["config"]
    assert call["language"]["sourceLanguage"] == "te" and call["serviceId"] == "svc-asr-te" and call["samplingRate"] == 16000


def test_transcribe_rejects_bad_audio(client, auth):
    assert _upload(client, auth, b"not audio").status_code == 415
    assert _upload(client, auth, make_wav(1.0, channels=2)).status_code == 415
    assert _upload(client, auth, make_wav(20.0)).status_code == 413  # > MAX_AUDIO_BYTES (400 kB) in test settings
    assert _upload(client, auth, make_wav(0.05)).status_code == 400
    r = client.post(f"{P}/voice/transcribe", data={"language": "te"}, headers=auth)
    assert r.status_code == 422  # missing file


def test_transcribe_no_speech_and_unsupported_language(client, auth, bhashini):
    bhashini.transcript = "   "
    r = _upload(client, auth, make_wav(1.0))
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_speech"
    r = _upload(client, auth, make_wav(1.0), language="sa-IN")  # Sanskrit has ASR
    assert r.status_code == 400  # empty transcript, not a crash
    bhashini.transcript = "ok"


def test_voice_requires_auth(client):
    assert client.post(f"{P}/voice/transcribe", files={"audio": ("a.wav", make_wav(1), "audio/wav")}).status_code == 401
    assert client.post(f"{P}/voice/synthesize", json={"text": "hi", "language": "en"}).status_code == 401


def test_synthesize_returns_wav_and_strips_markdown(client, auth, bhashini):
    r = client.post(f"{P}/voice/synthesize", json={"text": "## Hello\n**Namaste** [link](http://x.y)", "language": "hi"}, headers=auth)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content[:4] == b"RIFF"
    assert bhashini.tts_texts == ["Hello Namaste link"]


def test_synthesize_chunks_long_text_and_caches(client, auth, bhashini):
    text = " ".join(f"Sentence number {i} is here." for i in range(30))  # > 280 chars
    first = client.post(f"{P}/voice/synthesize", json={"text": text, "language": "en"}, headers=auth)
    assert first.status_code == 200
    n_calls = len(bhashini.tts_texts)
    assert n_calls >= 3 and all(len(t) <= 280 for t in bhashini.tts_texts)
    second = client.post(f"{P}/voice/synthesize", json={"text": text, "language": "en"}, headers=auth)
    assert second.content == first.content and len(bhashini.tts_texts) == n_calls  # served from cache


def test_synthesized_audio_is_always_standard_pcm16_even_if_the_provider_sends_float(client, auth, bhashini):
    """Regression for a bug the live Bhashini service exposed: it answers with 32-bit float audio."""
    import io
    import wave

    short = client.post(f"{P}/voice/synthesize", json={"text": "Hello there", "language": "en"}, headers=auth)
    with wave.open(io.BytesIO(short.content)) as w:  # would raise wave.Error on a float WAV
        assert (w.getsampwidth(), w.getnchannels(), w.getframerate()) == (2, 1, 8000)
    long = client.post(f"{P}/voice/synthesize", json={"text": " ".join(f"Sentence number {i} is here." for i in range(30)), "language": "en"}, headers=auth)
    assert long.status_code == 200  # joining several float chunks used to be impossible
    chunks = len(bhashini.tts_texts) - 1  # every request after the first (short) one is a chunk of the long text
    assert chunks >= 3
    with wave.open(io.BytesIO(long.content)) as w:
        assert w.getsampwidth() == 2
        assert w.getnframes() == 800 * chunks  # each fake chunk is 0.1 s at 8 kHz = 800 frames, joined end to end


def test_synthesize_uses_preferred_voice_gender(client, auth, bhashini):
    client.put(f"{P}/preferences", json={"tts_gender": "male"}, headers=auth)
    client.post(f"{P}/voice/synthesize", json={"text": "hello there", "language": "en"}, headers=auth)
    assert bhashini.compute_calls[-1]["pipelineTasks"][0]["config"]["gender"] == "male"


def test_synthesize_unsupported_language_and_empty_text(client, auth):
    r = client.post(f"{P}/voice/synthesize", json={"text": "hello", "language": "ur"}, headers=auth)  # no TTS for Urdu
    assert r.status_code == 400 and r.json()["error"]["code"] == "language_not_supported"
    r = client.post(f"{P}/voice/synthesize", json={"text": "```code```", "language": "en"}, headers=auth)
    assert r.status_code == 400


def test_bhashini_not_configured_gives_clear_503(make_client):
    from tests.conftest import login_guest

    c = make_client(bhashini_user_id="", bhashini_ulca_api_key="")
    h = login_guest(c)
    r = c.post(f"{P}/voice/synthesize", json={"text": "hello", "language": "en"}, headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "bhashini_not_configured"
    assert c.get(f"{P}/health").json()["bhashini_configured"] is False


def test_bhashini_outage_maps_to_502_over_http(llm):
    import httpx
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app
    from tests.conftest import login_guest
    from tests.fakes import fake_tools_client

    down = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(503, text="down")))
    app = create_app(Settings(_env_file=None), llm_client=llm.client(), bhashini_client=down, tools_client=fake_tools_client())
    with TestClient(app) as c:
        h = login_guest(c)
        r = c.post(f"{P}/voice/synthesize", json={"text": "hello", "language": "en"}, headers=h)
        assert r.status_code == 502 and r.json()["error"]["code"] == "bhashini_error"
        r = c.post(f"{P}/voice/transcribe", files={"audio": ("a.wav", make_wav(1), "audio/wav")}, data={"language": "en"}, headers=h)
        assert r.status_code == 502


@pytest.mark.parametrize("status,retryable", [(500, True), (401, True), (400, False)])
def test_bhashini_service_error_mapping(status, retryable):
    import httpx

    fake = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(status, text="x")))
    svc = BhashiniService(Settings(_env_file=None, bhashini_user_id="u", bhashini_ulca_api_key="k"), fake)
    with pytest.raises(UpstreamError) as exc:
        asyncio.run(svc.synthesize("hi", "en"))
    assert exc.value.retryable is retryable


def test_bhashini_pipeline_config_is_cached_per_language(bhashini):
    svc = BhashiniService(Settings(_env_file=None, bhashini_user_id="u", bhashini_ulca_api_key="k"), bhashini.client())

    async def go():
        await svc.synthesize("one", "en")
        await svc.synthesize("two", "en")
        await svc.synthesize("teen", "te")

    asyncio.run(go())
    assert bhashini.config_calls == 2  # en once (cached), te once


def test_bhashini_missing_model_is_reported():
    fake = FakeBhashini(no_model_for={"as"})
    svc = BhashiniService(Settings(_env_file=None, bhashini_user_id="u", bhashini_ulca_api_key="k"), fake.client())
    with pytest.raises(UpstreamError) as exc:
        asyncio.run(svc.synthesize("hello", "as"))
    assert exc.value.code == "bhashini_no_model"


def test_bhashini_unconfigured_service_raises():
    svc = BhashiniService(Settings(_env_file=None, bhashini_user_id="", bhashini_ulca_api_key=""))
    with pytest.raises(ServiceUnavailable):
        asyncio.run(svc.transcribe(make_wav(1), "en"))
