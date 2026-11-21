"""Live voice calls: Agora Conversational AI (faked here) + Murf Falcon settings, the call token, and the agent's brain endpoint."""
import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.utils.yesno import quick_yes_no
from tests.conftest import login_guest
from tests.fakes import FakeBhashini, FakeLLM, FakeOSM, fake_tools_client
from tests.test_healthcare import run
from tests.test_places_family_sos import plan

P = "/api/v1"
APP_ID, CERT = "a" * 32, "b" * 32
MURF_KEY, PUBLIC = "murf-secret-key-xyz", "https://abc.trycloudflare.com"


class FakeAgora:
    """Stand-in for Agora's REST API: records every request, answers like the real one."""

    def __init__(self, join_status: int = 200, join_body: dict | None = None):
        self.join_status, self.join_body = join_status, join_body
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/join"):
            if self.join_status != 200:
                return httpx.Response(self.join_status, json=self.join_body or {})
            return httpx.Response(200, json={"agent_id": f"agent-{len(self.requests)}", "create_ts": 1, "status": "RUNNING"})
        if request.url.path.endswith("/leave"):
            return httpx.Response(200)
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    @property
    def joins(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith("/join")]

    @property
    def leaves(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith("/leave")]


@contextmanager
def make(agora: FakeAgora | None = None, llm: FakeLLM | None = None, **settings):
    agora, llm = agora or FakeAgora(), llm or FakeLLM([{"content": "ok"}])
    base = dict(agora_app_id=APP_ID, agora_app_certificate=CERT, murf_api_key=MURF_KEY, agora_public_url=PUBLIC, llm_api_key="gsk-groq-secret")
    base.update(settings)
    app = create_app(
        Settings(_env_file=None, bhashini_user_id="u", bhashini_ulca_api_key="k", reminder_poll_seconds=0, seed_demo_providers=False, places_request_gap_seconds=0, **base),
        llm_client=llm.client(), bhashini_client=FakeBhashini().client(), tools_client=fake_tools_client(), places_client=FakeOSM().client(), agora_client=agora.client(),
    )
    with TestClient(app) as c:
        c.agora, c.llm = agora, llm
        yield c


def start(c, h, **body):
    return c.post(f"{P}/agora/session", json=body, headers=h)


def sse_text(resp) -> str:
    """The words an SSE stream of chat.completion.chunk events speaks."""
    out, done = "", False
    for line in resp.text.splitlines():
        if line == "data: [DONE]":
            done = True
        elif line.startswith("data: "):
            for ch in json.loads(line[6:])["choices"]:
                out += ch["delta"].get("content", "")
    assert done, "stream must end with [DONE]"
    return out


def agent_brain(c, token, text, history=()):
    msgs = [*history, {"role": "user", "content": text}]
    return c.post(f"{P}/agora/llm/chat/completions", json={"messages": msgs, "stream": True, "model": "x"}, headers={"Authorization": f"Bearer {token}"})


# =============================================================================== status & configuration
def test_status_reports_what_is_missing_and_the_mode():
    with make(agora_app_id="", agora_app_certificate="", murf_api_key="") as c:
        s = c.get(f"{P}/agora/status", headers=login_guest(c)).json()
        assert s["configured"] is False and s["mode"] == "unconfigured"
        assert all(k in s["note"] for k in ("AGORA_APP_ID", "AGORA_APP_CERTIFICATE", "MURF_API_KEY"))
    with make(agora_public_url="") as c:
        s = c.get(f"{P}/agora/status", headers=login_guest(c)).json()
        assert s["mode"] == "chat_only" and "AGORA_PUBLIC_URL" in s["note"] and s["configured"] is True
    with make() as c:
        s = c.get(f"{P}/agora/status", headers=login_guest(c)).json()
        assert s["mode"] == "tools" and s["note"] is None
        langs = {l["code"]: l for l in s["languages"]}
        assert set(langs) == {"en", "hi", "te", "ta", "kn", "ml", "bn", "mr", "gu", "pa"} and langs["te"]["voice"] == "Anisha" and langs["te"]["native_name"] == "తెలుగు"


def test_settings_validation():
    for bad in (dict(agora_public_url="http://insecure.example.com"), dict(murf_voices="not json"), dict(murf_voices="[1]"), dict(agora_asr_vendor="whisper")):
        with pytest.raises(ValueError):
            Settings(_env_file=None, **bad)
    assert Settings(_env_file=None, agora_app_id=APP_ID, agora_app_certificate=CERT, murf_api_key="k").agora_mode == "chat_only"


def test_murf_voice_can_be_overridden_per_language():
    with make(murf_voices='{"te": "Pooja"}') as c:
        h = login_guest(c)
        assert start(c, h, language="te").json()["voice"]["voice_id"] == "Pooja"
        assert start(c, h, language="hi").json()["voice"]["voice_id"] == "Ayushi"  # others keep the default


def test_starting_a_call_without_keys_is_a_clear_503():
    with make(agora_app_id="", agora_app_certificate="") as c:
        r = start(c, login_guest(c))
        assert r.status_code == 503 and r.json()["error"]["code"] == "agora_not_configured" and not c.agora.requests
    with make(murf_api_key="") as c:
        r = start(c, login_guest(c))
        assert r.status_code == 503 and r.json()["error"]["code"] == "murf_not_configured"


# =============================================================================== starting a call
def test_start_call_sends_agora_the_right_agent_configuration():
    with make() as c:
        h = login_guest(c)
        r = start(c, h, language="te")
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["app_id"] == APP_ID and out["mode"] == "tools" and out["language"] == "te" and out["voice"] == {"vendor": "murf", "voice_id": "Anisha", "locale": "te-IN"}
        assert out["uid"] != out["agent_uid"] and out["agent_uid"] == out["uid"] + 1 and out["expires_in"] == 3600 and out["greeting"].startswith("నమస్కారం")
        assert out["token"].startswith("007") and out["agent_id"].startswith("agent-")

        req = c.agora.requests[0]
        assert req.url.path == f"/api/conversational-ai-agent/v2/projects/{APP_ID}/join"
        assert req.headers["authorization"].startswith("agora token=007")  # token auth: no Customer ID/Secret needed
        body = c.agora.joins[0]
        props = body["properties"]
        assert body["name"].startswith("swasthya-ss-") and props["channel"] == out["channel"]
        assert props["agent_rtc_uid"] == str(out["agent_uid"]) and props["remote_rtc_uids"] == [str(out["uid"])] and props["idle_timeout"] == 120
        asr = props["asr"]  # the language plus Indian English (people mix), and place names the recogniser should favour
        assert asr["vendor"] == "ares" and asr["language"] == "te-IN,en-IN" and "Guntur" in asr["keywords"] and 0 < len(asr["keywords"]) <= 128
        assert props["tts"] == {"vendor": "murf", "params": {
            "api_key": MURF_KEY, "base_url": "wss://global.api.murf.ai/v1/speech/stream-input", "voiceId": "Anisha", "locale": "te-IN", "model": "FALCON", "sample_rate": 24000}}
        llm = props["llm"]
        assert llm["vendor"] == "custom" and llm["style"] == "openai" and llm["url"] == f"{PUBLIC}/api/v1/agora/llm/chat/completions"
        assert llm["greeting_message"] == out["greeting"] and llm["failure_message"].startswith("క్షమించండి") and "system_messages" not in llm


def test_the_browser_never_receives_a_secret():
    with make() as c:
        h = login_guest(c)
        raw = start(c, h).text
        for secret in (MURF_KEY, CERT, "gsk-groq-secret", "jwt"):
            assert secret not in raw


def test_the_token_given_to_agora_cannot_be_used_to_log_in():
    with make() as c:
        h = login_guest(c)
        start(c, h)
        call_token = c.agora.joins[0]["properties"]["llm"]["api_key"]
        assert c.get(f"{P}/auth/me", headers={"Authorization": f"Bearer {call_token}"}).status_code == 401
        # and the normal login token is not accepted as a call token either
        assert agent_brain(c, h["Authorization"].split()[1], "hello").status_code == 401


def test_without_a_public_url_the_agent_talks_to_the_llm_directly_and_is_told_it_has_no_tools():
    with make(agora_public_url="") as c:
        out = start(c, login_guest(c)).json()
        assert out["mode"] == "chat_only"
        llm = c.agora.joins[0]["properties"]["llm"]
        assert llm["url"] == "https://llm.test/v1/chat/completions" and llm["api_key"] == "gsk-groq-secret"
        system = llm["system_messages"][0]["content"]
        assert "spoken aloud" in system and "NO tools" in system and "112" in system
        assert llm["params"]["model"] == "test-model"


def test_sarvam_can_be_the_speech_to_text():
    with make(agora_asr_vendor="sarvam", sarvam_api_key="sarvam-key") as c:
        start(c, login_guest(c), language="hi")
        assert c.agora.joins[0]["properties"]["asr"] == {"vendor": "sarvam", "language": "hi-IN", "params": {"api_key": "sarvam-key", "language": "hi-IN"}}


def test_unsupported_language_and_conversation_ownership():
    with make() as c:
        h, other = login_guest(c), login_guest(c)
        r = start(c, h, language="or")
        assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_language"
        first = start(c, h, language="en").json()
        again = start(c, h, language="hi", conversation_id=first["conversation_id"]).json()
        assert again["conversation_id"] == first["conversation_id"]
        assert start(c, other, conversation_id=first["conversation_id"]).status_code == 404


def test_agora_errors_become_clear_messages():
    with make(FakeAgora(401, {"detail": "bad token"})) as c:
        r = start(c, login_guest(c))
        assert r.status_code == 502 and r.json()["error"]["code"] == "agora_auth_failed" and "AGORA_APP_CERTIFICATE" in r.json()["error"]["message"]
    with make(FakeAgora(400, {"detail": "Invalid value at properties.tts", "reason": "InvalidFieldValue"})) as c:
        r = start(c, login_guest(c)).json()["error"]
        assert r["code"] == "agora_error" and "InvalidFieldValue" in r["message"] and "properties.tts" in r["message"] and MURF_KEY not in r["message"]
    with make(FakeAgora(503)) as c:
        assert start(c, login_guest(c)).json()["error"]["code"] == "agora_error"


def test_hanging_up_calls_leave_once_and_only_for_the_owner():
    with make() as c:
        h, other = login_guest(c), login_guest(c)
        agent_id = start(c, h).json()["agent_id"]
        assert c.post(f"{P}/agora/session/{agent_id}/stop", headers=other).status_code == 204 and not c.agora.leaves  # not theirs: nothing happens
        assert c.post(f"{P}/agora/session/{agent_id}/stop", headers=h).status_code == 204
        assert len(c.agora.leaves) == 1 and c.agora.leaves[0].url.path.endswith(f"/agents/{agent_id}/leave")
        assert c.post(f"{P}/agora/session/{agent_id}/stop", headers=h).status_code == 204 and len(c.agora.leaves) == 1  # idempotent


# =============================================================================== the agent's brain
def test_agent_brain_streams_the_assistant_answer_in_openai_format():
    llm = FakeLLM([{"content": "Hello, how can I help you?"}])
    with make(llm=llm) as c:
        h = login_guest(c)
        out = start(c, h, language="en").json()
        token = c.agora.joins[0]["properties"]["llm"]["api_key"]
        r = agent_brain(c, token, "I have a fever", history=[{"role": "system", "content": "ignored"}, {"role": "assistant", "content": "Hello"}])
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert sse_text(r) == "Hello, how can I help you?"
        first = json.loads(r.text.splitlines()[0][6:])
        assert first["object"] == "chat.completion.chunk" and first["choices"][0]["delta"]["role"] == "assistant"
        convo = c.get(f"{P}/conversations/{out['conversation_id']}", headers=h).json()
        user_msgs = [m for m in convo["messages"] if m["role"] == "user"]
        assert [m["content"] for m in user_msgs] == ["I have a fever"] and user_msgs[0]["input_mode"] == "voice"  # saved like any other turn
        system = next(q for q in llm.requests if q.get("stream"))["messages"][0]["content"]
        assert "spoken aloud" in system  # the voice style is used


def test_agent_brain_rejects_missing_or_bad_tokens_and_survives_empty_input():
    with make() as c:
        assert c.post(f"{P}/agora/llm/chat/completions", json={"messages": []}).status_code == 401
        assert agent_brain(c, "garbage", "hi").status_code == 401
        token = (start(c, login_guest(c)), c.agora.joins[0]["properties"]["llm"]["api_key"])[1]
        r = c.post(f"{P}/agora/llm/chat/completions", json={"messages": [{"role": "assistant", "content": "only me"}]}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and sse_text(r) == ""


def test_agent_failure_is_spoken_not_silent():
    llm = FakeLLM([{"error": 500}] * 6)
    with make(llm=llm) as c:
        start(c, login_guest(c), language="hi")
        token = c.agora.joins[0]["properties"]["llm"]["api_key"]
        assert sse_text(agent_brain(c, token, "नमस्ते")).startswith("माफ़ कीजिए")


def _call_with_a_visit_to_cancel(c, h, language="en"):
    ref = plan(c, h).json()["ref"]
    start(c, h, language=language)
    return ref, c.agora.joins[-1]["properties"]["llm"]["api_key"]


def _status(c, h, ref):
    return next(a["status"] for a in c.get(f"{P}/appointments?scope=all", headers=h).json()["items"] if a["ref"] == ref)


def test_spoken_yes_confirms_a_pending_action_and_no_cancels_it():
    with make() as c:
        h = login_guest(c)
        ref, token = _call_with_a_visit_to_cancel(c, h)
        c.llm.script = [{"content": "I will cancel it.", "tool_calls": [("cancel_appointment", {"reference": ref})]}]
        said = sse_text(agent_brain(c, token, "please cancel my visit"))
        assert "I will cancel it." in said and said.endswith("Please say yes to confirm, or no to cancel.")  # the app asks, in words
        assert _status(c, h, ref) == "booked"  # nothing happens before the answer

        c.llm.script = [{"content": "Done, it is cancelled."}]
        assert sse_text(agent_brain(c, token, "yes please")) == "Done, it is cancelled." and _status(c, h, ref) == "cancelled"


def test_spoken_no_leaves_the_visit_alone_and_an_unclear_answer_asks_again():
    with make() as c:
        h = login_guest(c)
        ref, token = _call_with_a_visit_to_cancel(c, h)
        c.llm.script = [{"tool_calls": [("cancel_appointment", {"reference": ref})]}]
        agent_brain(c, token, "cancel my visit")
        c.llm.script = [{"content": "Unclear"}]  # the yes/no judge (an LLM) cannot decide either
        again = sse_text(agent_brain(c, token, "banana"))
        assert again == "Please say yes to confirm, or no to cancel." and _status(c, h, ref) == "booked"
        c.llm.script = [{"content": "Okay, I kept it."}]
        assert sse_text(agent_brain(c, token, "no, don't")) == "Okay, I kept it." and _status(c, h, ref) == "booked"


def test_confirmation_prompt_is_spoken_in_the_callers_language():
    with make() as c:
        h = login_guest(c)
        ref, token = _call_with_a_visit_to_cancel(c, h, language="te")
        c.llm.script = [{"tool_calls": [("cancel_appointment", {"reference": ref})]}]
        said = sse_text(agent_brain(c, token, "రద్దు చేయండి"))
        assert said.strip().endswith("నిర్ధారించడానికి అవును అని చెప్పండి, రద్దు చేయడానికి కాదు అని చెప్పండి.")
        c.llm.script = [{"content": "సరే"}]
        agent_brain(c, token, "అవును")
        assert _status(c, h, ref) == "cancelled"


# =============================================================================== understanding yes / no
@pytest.mark.parametrize("text", ["yes", "Yes please", "okay", "sure, go ahead", "haan", "हाँ", "అవును", "సరే", "ஆமாம்", "ಹೌದು", "അതെ", "হ্যাঁ", "હા", "ਹਾਂ", "avunu", "book it"])
def test_yes_in_many_languages(text):
    assert quick_yes_no(text) == "yes"


@pytest.mark.parametrize("text", ["no", "No thanks", "cancel", "don't", "do not book it", "nahi", "नहीं", "వద్దు", "కాదు", "இல்லை", "ಬೇಡ", "ഇല്ല", "না", "ના", "ਨਹੀਂ"])
def test_no_in_many_languages(text):
    assert quick_yes_no(text) == "no"


@pytest.mark.parametrize("text", ["", "banana", "what time is it", "yes but no", "maybe later"])
def test_unclear_answers_are_not_guessed(text):
    assert quick_yes_no(text) == "other"
