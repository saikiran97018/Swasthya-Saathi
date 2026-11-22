"""Bhashini first, Sarvam as the automatic backup (or the other way round)."""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ServiceUnavailable, UpstreamError
from app.main import create_app
from app.services.speech_failover import FailoverSpeechProvider
from tests.conftest import login_guest
from tests.fakes import FakeBhashini, FakeLLM, FakeSarvam, fake_tools_client, make_wav

P = "/api/v1"


# ------------------------------------------------------------------ unit: the failover provider itself
class Fake:
    def __init__(self, name, *, configured=True, languages=("en", "te", "hi"), fail=False, text="hello", max_seconds=None):
        self.name, self.configured, self.languages, self.fail, self.text, self.max_audio_seconds = name, configured, set(languages), fail, text, max_seconds
        self.calls = 0

    def supports(self, language, task):
        return language in self.languages

    async def transcribe(self, wav, language, sample_rate=16000):
        self.calls += 1
        if self.fail:
            raise UpstreamError(f"{self.name} down", code=f"{self.name}_error")
        return self.text

    async def synthesize(self, text, language, gender="female"):
        self.calls += 1
        if self.fail:
            raise UpstreamError(f"{self.name} down", code=f"{self.name}_error")
        return f"audio-from-{self.name}".encode()

    async def aclose(self):
        pass


def run(coro):
    return asyncio.run(coro)


def test_primary_is_used_and_backup_untouched_when_healthy():
    a, b = Fake("bhashini"), Fake("sarvam")
    f = FailoverSpeechProvider(a, b)
    assert run(f.synthesize("hi", "en")) == b"audio-from-bhashini" and (a.calls, b.calls) == (1, 0)
    assert f.name == "bhashini" and f.fallback_name == "sarvam"


def test_backup_takes_over_when_primary_fails():
    a, b = Fake("bhashini", fail=True), Fake("sarvam", text="from sarvam")
    f = FailoverSpeechProvider(a, b)
    assert run(f.transcribe(b"x", "te")) == "from sarvam"
    assert run(f.synthesize("hi", "te")) == b"audio-from-sarvam"
    assert (a.calls, b.calls) == (2, 2)


def test_unconfigured_or_language_less_providers_are_skipped_without_a_call():
    a, b = Fake("bhashini", configured=False), Fake("sarvam")
    assert run(FailoverSpeechProvider(a, b).synthesize("hi", "en")) == b"audio-from-sarvam" and a.calls == 0
    only_en, other = Fake("bhashini", languages=("en",)), Fake("sarvam")
    assert run(FailoverSpeechProvider(only_en, other).synthesize("hi", "hi")) == b"audio-from-sarvam" and only_en.calls == 0


def test_nobody_can_serve_the_request():
    f = FailoverSpeechProvider(Fake("bhashini", configured=False), Fake("sarvam", languages=("en",)))
    with pytest.raises(ServiceUnavailable):
        run(f.synthesize("hi", "te"))
    assert not f.supports("te", "tts") and f.supports("en", "tts")


def test_when_both_fail_the_last_error_is_raised():
    f = FailoverSpeechProvider(Fake("bhashini", fail=True), Fake("sarvam", fail=True))
    with pytest.raises(UpstreamError) as exc:
        run(f.synthesize("hi", "en"))
    assert exc.value.code == "sarvam_error"


def test_silence_is_not_a_failure_so_no_second_paid_call():
    a, b = Fake("bhashini", text=""), Fake("sarvam", text="should not be asked")
    assert run(FailoverSpeechProvider(a, b).transcribe(b"x", "en")) == "" and b.calls == 0


def test_recording_limit_follows_the_provider_that_will_be_tried_first():
    assert FailoverSpeechProvider(Fake("bhashini", max_seconds=None), Fake("sarvam", max_seconds=30)).max_audio_seconds is None
    assert FailoverSpeechProvider(Fake("sarvam", max_seconds=30), Fake("bhashini")).max_audio_seconds == 30
    assert FailoverSpeechProvider(Fake("bhashini", configured=False), Fake("sarvam", max_seconds=30)).max_audio_seconds == 30


# ------------------------------------------------------------------ settings: who is primary, who is the backup
def S(**kw):
    base = dict(_env_file=None, bhashini_user_id="", bhashini_ulca_api_key="", sarvam_api_key="")
    return Settings(**{**base, **kw})


BOTH = dict(bhashini_user_id="u", bhashini_ulca_api_key="k", sarvam_api_key="s")


@pytest.mark.parametrize(
    "kw,primary,backup",
    [
        ({}, "bhashini", None),
        (dict(bhashini_user_id="u", bhashini_ulca_api_key="k"), "bhashini", None),  # a backup needs credentials
        (dict(sarvam_api_key="s"), "sarvam", None),
        (dict(**BOTH), "sarvam", "bhashini"),  # auto prefers Sarvam, Bhashini backs it up
        (dict(**BOTH, speech_provider="bhashini"), "bhashini", "sarvam"),  # what this project uses
        (dict(**BOTH, speech_provider="bhashini", speech_fallback_provider="none"), "bhashini", None),
        (dict(**BOTH, speech_provider="bhashini", speech_fallback_provider="sarvam"), "bhashini", "sarvam"),
        (dict(**BOTH, speech_provider="bhashini", speech_fallback_provider="bhashini"), "bhashini", None),  # not itself
        (dict(bhashini_user_id="u", bhashini_ulca_api_key="k", speech_provider="bhashini", speech_fallback_provider="sarvam"), "bhashini", None),
    ],
)
def test_primary_and_backup_resolution(kw, primary, backup):
    s = S(**kw)
    assert (s.resolved_speech_provider, s.resolved_speech_fallback) == (primary, backup)


def test_invalid_fallback_value_is_rejected():
    with pytest.raises(ValueError):
        S(speech_fallback_provider="whisper")


# ------------------------------------------------------------------ end to end through the HTTP API
def app_with(bhashini_client, sarvam, **kw):
    settings = Settings(_env_file=None, bhashini_user_id="u", bhashini_ulca_api_key="k", sarvam_api_key="sk-test", speech_provider="bhashini",
                        max_audio_bytes=2_000_000, reminder_poll_seconds=0, **kw)
    return create_app(settings, llm_client=FakeLLM().client(), bhashini_client=bhashini_client, sarvam_client=sarvam.client(), tools_client=fake_tools_client())


def down():
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503, text="down")))


def test_health_reports_main_and_backup():
    with TestClient(app_with(FakeBhashini().client(), FakeSarvam())) as c:
        h = c.get(f"{P}/health").json()
        assert h["speech_provider"] == "bhashini" and h["speech_fallback_provider"] == "sarvam" and h["speech_configured"] is True


def test_health_without_a_backup_reports_none(client):
    assert client.get(f"{P}/health").json()["speech_fallback_provider"] is None


def test_voice_keeps_working_through_sarvam_when_bhashini_is_down():
    sarvam = FakeSarvam(transcript="నాకు జ్వరం ఉంది")
    with TestClient(app_with(down(), sarvam)) as c:
        h = login_guest(c)
        said = c.post(f"{P}/voice/synthesize", json={"text": "నమస్కారం", "language": "te"}, headers=h)
        assert said.status_code == 200 and said.content[:4] == b"RIFF" and len(sarvam.tts_calls) == 1
        heard = c.post(f"{P}/voice/transcribe", files={"audio": ("a.wav", make_wav(2.0), "audio/wav")}, data={"language": "te"}, headers=h)
        assert heard.status_code == 200 and heard.json()["text"] == "నాకు జ్వరం ఉంది" and len(sarvam.stt_calls) == 1  # Sarvam answered (it detects the language itself)


def test_backup_is_not_called_while_bhashini_is_healthy():
    sarvam = FakeSarvam()
    with TestClient(app_with(FakeBhashini().client(), sarvam)) as c:
        h = login_guest(c)
        assert c.post(f"{P}/voice/synthesize", json={"text": "hello there", "language": "en"}, headers=h).status_code == 200
        assert c.post(f"{P}/voice/transcribe", files={"audio": ("a.wav", make_wav(1.0), "audio/wav")}, data={"language": "en"}, headers=h).status_code == 200
    assert sarvam.tts_calls == [] and sarvam.stt_calls == []


def test_when_both_providers_are_down_the_user_gets_a_clear_502():
    with TestClient(app_with(down(), FakeSarvam(status=503))) as c:
        r = c.post(f"{P}/voice/synthesize", json={"text": "hello", "language": "en"}, headers=login_guest(c))
        assert r.status_code == 502 and r.json()["error"]["code"] == "sarvam_error"


def test_language_list_is_the_union_of_what_either_provider_can_do():
    with TestClient(app_with(FakeBhashini().client(), FakeSarvam())) as c:
        langs = {l["code"]: l for l in c.get(f"{P}/languages").json()}
        assert langs["as"]["tts"] is True  # Assamese: Sarvam cannot speak it, Bhashini can
        assert langs["ur"]["tts"] is False  # neither can speak Urdu
        assert all(langs[x]["asr"] for x in ("te", "hi", "ta", "or", "as", "ur", "sa"))
