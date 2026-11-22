"""Sarvam speech provider + Groq -> Sarvam LLM failover."""
import asyncio
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import UpstreamError
from app.main import create_app
from app.services.llm_service import LLMService
from tests.conftest import login_guest
from tests.fakes import FakeBhashini, FakeLLM, FakeSarvam, fake_tools_client, make_wav

P = "/api/v1"


@pytest.fixture
def no_sleep(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr("app.services.llm_service.asyncio.sleep", instant)


# ============================================================================== speech: Sarvam
@contextmanager
def sarvam_app(sarvam: FakeSarvam, llm: FakeLLM | None = None, **settings):
    llm = llm or FakeLLM([{"content": "ok"}])
    app = create_app(
        # speech_fallback_provider="none": these tests check Sarvam on its own (backup behaviour: test_speech_failover.py)
        Settings(_env_file=None, sarvam_api_key="sk-sarvam-test", max_audio_bytes=2_000_000, **{"speech_fallback_provider": "none", **settings}),
        llm_client=llm.client(), bhashini_client=FakeBhashini().client(), sarvam_client=sarvam.client(), tools_client=fake_tools_client(),
    )
    with TestClient(app) as c:
        yield c, login_guest(c)


def upload(c, auth, wav, language="te"):
    return c.post(f"{P}/voice/transcribe", files={"audio": ("a.wav", wav, "audio/wav")}, data={"language": language}, headers=auth)


def test_provider_selection():
    assert Settings(_env_file=None, sarvam_api_key="k").resolved_speech_provider == "sarvam"  # auto + key
    assert Settings(_env_file=None, sarvam_api_key="").resolved_speech_provider == "bhashini"  # auto, no key
    assert Settings(_env_file=None, sarvam_api_key="k", speech_provider="bhashini").resolved_speech_provider == "bhashini"
    assert Settings(_env_file=None, sarvam_api_key="", speech_provider="sarvam").resolved_speech_provider == "sarvam"
    with pytest.raises(ValueError):
        Settings(_env_file=None, speech_provider="whisper")


def test_health_and_languages_reflect_the_active_provider():
    with sarvam_app(FakeSarvam()) as (c, auth):
        h = c.get(f"{P}/health").json()
        assert h["speech_provider"] == "sarvam" and h["speech_configured"] is True and h["sarvam_configured"] is True
        assert h["max_audio_seconds"] == 30  # Sarvam REST limit is stricter than our 60 s
        langs = {l["code"]: l for l in c.get(f"{P}/languages").json()}
        assert langs["te"]["asr"] and langs["te"]["tts"] and langs["en"]["asr"] and langs["en"]["tts"]
        for code in ("as", "ur", "sa"):  # Sarvam can listen to these but has no voice for them
            assert langs[code]["asr"] is True and langs[code]["tts"] is False, code


def test_bhashini_provider_keeps_its_own_capabilities(client):
    h = client.get(f"{P}/health").json()
    assert h["speech_provider"] == "bhashini" and h["max_audio_seconds"] == 60
    langs = {l["code"]: l for l in client.get(f"{P}/languages").json()}
    assert langs["as"]["tts"] is True and langs["ur"]["tts"] is False


def test_transcribe_sends_the_documented_request():
    sarvam = FakeSarvam(transcript="నాకు రేషన్ కార్డ్ కావాలి")
    with sarvam_app(sarvam, sarvam_stt_autodetect=False, sarvam_stt_mode="transcribe") as (c, auth):  # the fixed-language setting
        r = upload(c, auth, make_wav(2.0))
    assert r.status_code == 200 and r.json() == {"text": "నాకు రేషన్ కార్డ్ కావాలి", "language": "te", "duration_seconds": 2.0}
    f = sarvam.stt_calls[0]
    assert f["model"] == "saaras:v4" and f["mode"] == "transcribe" and f["language_code"] == "te-IN"


def test_by_default_sarvam_detects_the_language_and_keeps_english_words_in_english():
    sarvam = FakeSarvam(transcript="నాకు 2 రోజులుగా జ్వరం ఉంది, Guntur-లో మంచి doctor ఉన్నారా?")
    with sarvam_app(sarvam) as (c, auth):
        assert upload(c, auth, make_wav(2.0), language="te").status_code == 200
        assert upload(c, auth, make_wav(2.0), language="hi").status_code == 200  # a Hindi speaker with Telugu selected is still understood
    assert all(f["mode"] == "codemix" and "language_code" not in f for f in sarvam.stt_calls)


def test_language_codes_are_mapped_to_sarvam_spelling():
    sarvam = FakeSarvam()
    with sarvam_app(sarvam, sarvam_stt_autodetect=False) as (c, auth):
        for ours in ("or", "hi", "en", "ml"):
            assert upload(c, auth, make_wav(1.0), language=ours).status_code == 200
    assert [f["language_code"] for f in sarvam.stt_calls] == ["od-IN", "hi-IN", "en-IN", "ml-IN"]  # Odia is od-IN, not or-IN


def test_sarvam_30_second_limit_is_enforced_before_calling_the_api():
    sarvam = FakeSarvam()
    with sarvam_app(sarvam) as (c, auth):
        assert upload(c, auth, make_wav(29.0)).status_code == 200
        too_long = upload(c, auth, make_wav(31.0))
        assert too_long.status_code == 413 and "30 second" in too_long.json()["error"]["message"]
    assert len(sarvam.stt_calls) == 1  # the long upload never reached Sarvam


def test_empty_transcript_is_reported_as_no_speech():
    with sarvam_app(FakeSarvam(transcript="  ")) as (c, auth):
        r = upload(c, auth, make_wav(1.0))
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_speech"


def test_synthesize_sends_model_speaker_and_decodes_base64_wav():
    sarvam = FakeSarvam()
    with sarvam_app(sarvam) as (c, auth):
        r = c.post(f"{P}/voice/synthesize", json={"text": "## నమస్కారం\n**మీ** అపాయింట్‌మెంట్ రేపు ఉంది", "language": "te"}, headers=auth)
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content[:4] == b"RIFF"
        c.post(f"{P}/voice/synthesize", json={"text": "hello there", "language": "en", "gender": "male"}, headers=auth)
    first, second = sarvam.tts_calls
    assert first["language_code"] == "te-IN" and first["model"] == "bulbul:v3" and first["speaker"] == "priya"
    assert first["output_audio_codec"] == "wav" and first["speech_sample_rate"] == 22050 and "#" not in first["text"] and "*" not in first["text"]
    assert second["language_code"] == "en-IN" and second["speaker"] == "shubh"  # male default


def test_synthesize_long_text_is_chunked_and_cached():
    sarvam = FakeSarvam()
    text = " ".join(f"Sentence number {i} is here." for i in range(30))
    with sarvam_app(sarvam) as (c, auth):
        a = c.post(f"{P}/voice/synthesize", json={"text": text, "language": "en"}, headers=auth)
        n = len(sarvam.tts_calls)
        b = c.post(f"{P}/voice/synthesize", json={"text": text, "language": "en"}, headers=auth)
    assert n >= 3 and all(len(t["text"]) <= 280 for t in sarvam.tts_calls) and a.content == b.content and len(sarvam.tts_calls) == n


def test_languages_without_a_sarvam_voice_are_refused_cleanly():
    with sarvam_app(FakeSarvam()) as (c, auth):
        r = c.post(f"{P}/voice/synthesize", json={"text": "hello", "language": "ur"}, headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "language_not_supported"


@pytest.mark.parametrize(
    "status,code,http",
    [(403, "sarvam_auth_failed", 502), (402, "sarvam_no_credits", 502), (429, "sarvam_rate_limited", 502), (500, "sarvam_error", 502)],
)
def test_sarvam_errors_are_mapped(status, code, http):
    with sarvam_app(FakeSarvam(status=status)) as (c, auth):
        r = c.post(f"{P}/voice/synthesize", json={"text": "hello", "language": "en"}, headers=auth)
    assert r.status_code == http and r.json()["error"]["code"] == code


def test_sarvam_400_message_is_passed_on_to_help_debugging():
    with sarvam_app(FakeSarvam(status=400, error_message="Speaker 'priya' is not valid for model")) as (c, auth):
        r = c.post(f"{P}/voice/synthesize", json={"text": "hello", "language": "en"}, headers=auth)
    assert "Speaker 'priya' is not valid" in r.json()["error"]["message"]


def test_sarvam_selected_without_key_gives_clear_503(llm):
    app = create_app(Settings(_env_file=None, speech_provider="sarvam", sarvam_api_key="", speech_fallback_provider="none"), llm_client=llm.client(), tools_client=fake_tools_client())
    with TestClient(app) as c:
        h = login_guest(c)
        r = c.post(f"{P}/voice/synthesize", json={"text": "hi", "language": "en"}, headers=h)
        assert r.status_code == 503 and r.json()["error"]["code"] == "sarvam_not_configured" and "SARVAM_API_KEY" in r.json()["error"]["message"]
        assert c.get(f"{P}/health").json()["speech_configured"] is False


def test_sarvam_retryable_flags():
    from app.services.sarvam_service import SarvamService

    def svc(status):
        return SarvamService(Settings(_env_file=None, sarvam_api_key="k"), FakeSarvam(status=status).client())

    for status, retryable in [(429, True), (503, True), (402, False), (403, False)]:
        with pytest.raises(UpstreamError) as exc:
            asyncio.run(svc(status).synthesize("hi", "en"))
        assert exc.value.retryable is retryable, status


# ============================================================================ LLM failover
def failover_app(primary: FakeLLM, fallback: FakeLLM, **settings):
    base = dict(
        llm_base_url="https://groq.test/openai/v1", llm_api_key="gsk-primary", llm_model="llama-3.3-70b-versatile",
        llm_fallback_base_url="https://sarvam.test/v1", llm_fallback_api_key="sk-sarvam", llm_fallback_model="sarvam-105b-conversations",
        bhashini_user_id="u", bhashini_ulca_api_key="k", reminder_poll_seconds=0,
    )
    base.update(settings)
    app = create_app(Settings(_env_file=None, **base), llm_client=primary.client(), llm_fallback_client=fallback.client(),
                     bhashini_client=FakeBhashini().client(), tools_client=fake_tools_client())
    return TestClient(app)


def chat(c, h, msg="hello"):
    return c.post(f"{P}/chat", json={"message": msg}, headers=h)


def test_rate_limited_primary_fails_over_immediately_to_the_fallback():
    groq, sarvam = FakeLLM([{"error": 429}]), FakeLLM([{"content": "Namaste from Sarvam"}])
    with failover_app(groq, sarvam) as c:
        h = login_guest(c)
        r = chat(c, h)
        assert r.status_code == 200 and r.json()["assistant_message"]["content"] == "Namaste from Sarvam"
        assert groq.streaming_calls == 1 and sarvam.streaming_calls == 1  # no pointless retries against a rate-limited primary
        # each provider got its own model and key
        assert groq.requests[0]["model"] == "llama-3.3-70b-versatile" and groq.auth_headers[0] == "Bearer gsk-primary"
        sv = next(r for r in sarvam.requests if r.get("stream"))
        assert sv["model"] == "sarvam-105b-conversations" and sarvam.auth_headers[0] == "Bearer sk-sarvam"
        run = c.get(f"{P}/agents/executions", headers=h).json()["items"][0]
        assert run["model"] == "sarvam-105b-conversations" and run["status"] == "completed"  # honest record of who answered
        assert c.get(f"{P}/health").json()["llm_fallback_model"] == "sarvam-105b-conversations"


def test_server_errors_are_retried_once_then_fail_over(no_sleep):
    groq, sarvam = FakeLLM([{"error": 503}, {"error": 503}]), FakeLLM([{"content": "backup answer"}])
    with failover_app(groq, sarvam) as c:
        h = login_guest(c)
        assert chat(c, h).json()["assistant_message"]["content"] == "backup answer"
    assert groq.streaming_calls == 2 and sarvam.streaming_calls == 1


def test_bad_primary_key_also_fails_over():
    groq, sarvam = FakeLLM([{"error": 401}]), FakeLLM([{"content": "still working"}])
    with failover_app(groq, sarvam) as c:
        assert chat(c, login_guest(c)).json()["assistant_message"]["content"] == "still working"


def test_fallback_is_not_touched_when_the_primary_works():
    groq, sarvam = FakeLLM([{"content": "primary answer"}]), FakeLLM([{"content": "never used"}])
    with failover_app(groq, sarvam) as c:
        h = login_guest(c)
        assert chat(c, h).json()["assistant_message"]["content"] == "primary answer"
        assert c.get(f"{P}/agents/executions", headers=h).json()["items"][0]["model"] == "llama-3.3-70b-versatile"
    assert sarvam.streaming_calls == 0


def test_when_both_fail_the_error_is_reported(no_sleep):
    groq, sarvam = FakeLLM([{"error": 429}]), FakeLLM([{"error": 500}, {"error": 500}, {"error": 500}])
    with failover_app(groq, sarvam) as c:
        r = chat(c, login_guest(c))
        assert r.status_code == 502 and r.json()["error"]["code"] == "llm_error"
    assert groq.streaming_calls == 1 and sarvam.streaming_calls == 3


def test_tool_calls_work_through_the_fallback_model():
    groq = FakeLLM([{"error": 429}])
    sarvam = FakeLLM([{"tool_calls": [("search_knowledge_base", {"query": "Ayushman card"})]}, {"content": "Check eligibility on the PM-JAY site."}])
    with failover_app(groq, sarvam) as c:
        r = chat(c, login_guest(c), "How do I get an Ayushman card?").json()
    assert r["assistant_message"]["source"] == "tool" and r["tool_executions"][0]["status"] == "success"


def test_malformed_tool_call_goes_to_the_backup_model_with_tools_still_enabled():
    bad = {"error": 400, "body": '{"error":{"message":"Tool call validation failed: parameters for tool assess_urgency did not match schema","code":"tool_use_failed"}}'}
    groq, sarvam = FakeLLM([bad]), FakeLLM([{"content": "backup answered"}])
    with failover_app(groq, sarvam) as c:
        assert chat(c, login_guest(c)).json()["assistant_message"]["content"] == "backup answered"
    assert groq.streaming_calls == 1  # not retried on the same model without tools (that gave empty answers)
    assert next(r for r in sarvam.requests if r.get("stream")).get("tools")


def test_empty_answer_is_retried_then_handed_to_the_backup(no_sleep):
    groq, sarvam = FakeLLM([{"content": ""}, {"content": ""}]), FakeLLM([{"content": "backup answered"}])
    with failover_app(groq, sarvam) as c:
        assert chat(c, login_guest(c)).json()["assistant_message"]["content"] == "backup answered"
    assert groq.streaming_calls == 2 and sarvam.streaming_calls == 1


def test_error_reported_inside_a_200_stream_is_a_failure_not_an_empty_reply():
    groq = FakeLLM([{"stream_error": {"message": "Rate limit reached", "code": 429}}])
    sarvam = FakeLLM([{"content": "backup answered"}])
    with failover_app(groq, sarvam) as c:
        assert chat(c, login_guest(c)).json()["assistant_message"]["content"] == "backup answered"
    assert groq.streaming_calls == 1


def test_a_healthy_primary_stream_is_never_mixed_with_the_fallback():
    groq, sarvam = FakeLLM([{"content": "one two three four"}]), FakeLLM([{"content": "SHOULD NOT APPEAR"}])
    with failover_app(groq, sarvam) as c:
        h = login_guest(c)
        with c.websocket_connect(f"{P}/ws/chat?token={h['Authorization'].split()[1]}") as ws:
            ws.send_json({"type": "message", "text": "hi"})
            text = ""
            while True:
                ev = ws.receive_json()
                text += ev.get("delta", "")
                if ev["type"] == "done":
                    break
    assert text == "one two three four"


def test_extra_body_is_sent_per_target():
    groq, sarvam = FakeLLM([{"error": 429}]), FakeLLM([{"content": "ok"}])
    with failover_app(groq, sarvam, llm_extra_body='{"reasoning_effort": "low"}', llm_fallback_extra_body='{"reasoning_effort": null}') as c:
        chat(c, login_guest(c))
    assert groq.requests[0]["reasoning_effort"] == "low"
    sv = next(r for r in sarvam.requests if r.get("stream"))
    assert "reasoning_effort" in sv and sv["reasoning_effort"] is None  # explicit null turns Sarvam's reasoning off


def test_invalid_extra_body_fails_fast_at_startup():
    for field in ("llm_extra_body", "llm_fallback_extra_body"):
        with pytest.raises(ValueError):
            Settings(_env_file=None, **{field: "not json"})
        with pytest.raises(ValueError):
            Settings(_env_file=None, **{field: "[1, 2]"})


def test_only_the_fallback_configured_still_works():
    sarvam = FakeLLM([{"content": "Sarvam only"}])
    app = create_app(
        Settings(_env_file=None, llm_api_key="", llm_base_url="https://groq.test/openai/v1", llm_fallback_base_url="https://sarvam.test/v1",
                 llm_fallback_api_key="sk", llm_fallback_model="sarvam-105b-conversations", reminder_poll_seconds=0),
        llm_client=FakeLLM().client(), llm_fallback_client=sarvam.client(), bhashini_client=FakeBhashini().client(), tools_client=fake_tools_client(),
    )
    with TestClient(app) as c:
        h = login_guest(c)
        health = c.get(f"{P}/health").json()
        assert health["llm_configured"] and health["llm_model"] == "sarvam-105b-conversations" and health["llm_fallback_model"] is None
        assert chat(c, h).json()["assistant_message"]["content"] == "Sarvam only"


def test_nothing_configured_is_a_clear_error():
    app = create_app(Settings(_env_file=None, llm_api_key="", llm_fallback_api_key="", reminder_poll_seconds=0), llm_client=FakeLLM().client(), tools_client=fake_tools_client())
    with TestClient(app) as c:
        r = chat(c, login_guest(c))
        assert r.status_code == 503 and r.json()["error"]["code"] == "llm_not_configured"


def test_non_streaming_calls_also_fail_over():
    primary, fallback = FakeLLM(), FakeLLM(title="Fallback title")
    primary.fail_non_streaming = 500
    svc = LLMService(Settings(_env_file=None, llm_api_key="p", llm_base_url="https://a.test/v1", llm_fallback_base_url="https://b.test/v1", llm_fallback_api_key="f", llm_fallback_model="m2"),
                     primary.client(), fallback.client())
    assert asyncio.run(svc.complete([{"role": "user", "content": "title?"}])) == "Fallback title"


def test_reminder_translation_uses_the_fallback_when_the_primary_is_down(no_sleep):
    """End-to-end: a Telugu reminder is still translated when Groq is down, thanks to Sarvam."""
    from datetime import datetime, timedelta

    from app.services import scheduling as sched
    from tests.test_healthcare import appointments, book, first_slot, new_user, when

    groq, sarvam = FakeLLM(), FakeLLM(title="రేపు మీ అపాయింట్‌మెంట్")
    groq.fail_non_streaming = 500
    with failover_app(groq, sarvam) as c:
        h, _ = new_user(c)
        slot = first_slot(c, h, days_ahead=3)
        groq.script = [{"content": "Booking.", "tool_calls": [("book_appointment", {
            "provider_code": "HC-GNT-01", "slot_start": slot, "patient_name": "Ravi Kumar", "patient_mobile": "9876543210", "reason": "fever"})]}]
        r = c.post(f"{P}/chat", json={"message": "నాకు డాక్టర్ కావాలి", "language": "te"}, headers=h).json()
        pend = r["pending_confirmation"]
        groq.script = [{"content": "Done."}]
        c.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": True}, headers=h)
        a = appointments(c, h)[0]
        c.portal.call(c.app.state.reminder_service.deliver_due, when(a) - timedelta(hours=23))
        msg = c.get(f"{P}/notifications", headers=h).json()["items"][0]["message"]
    assert msg == "రేపు మీ అపాయింట్‌మెంట్"

