"""End-to-end agent behaviour over REST: answers, tools, confirmation, language, memory, errors."""
import pytest

from tests.conftest import login_guest

P = "/api/v1"

ABHA_FIELDS = {"full_name": "Lakshmi", "mobile": "9876543210", "state": "Andhra Pradesh", "district": "Guntur", "mobile_linked_to_aadhaar": "yes"}
SUBMIT_CALL = ("submit_service_request", {"form_id": "abha_creation_help", "fields": ABHA_FIELDS})


def say(client, auth, message="hi", **kw):
    return client.post(f"{P}/chat", json={"message": message, **kw}, headers=auth)


def system_prompt(llm, call=-1) -> str:
    streaming = [r for r in llm.requests if r.get("stream")]
    return streaming[call]["messages"][0]["content"]


# ------------------------------------------------------------------ basic answers
def test_plain_answer_is_persisted_with_title_and_history(client, auth, llm):
    llm.script = [{"content": "Hello! How can I help?"}]
    r = say(client, auth, "hi there")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assistant_message"]["content"] == "Hello! How can I help?"
    assert body["assistant_message"]["source"] == "ai" and body["assistant_message"]["tools_used"] == []
    assert body["user_message"]["content"] == "hi there"
    assert body["conversation"]["title"] == "Test Title"  # LLM-generated
    assert body["language"] == "en" and body["execution_id"]

    detail = client.get(f"{P}/conversations/{body['conversation']['id']}", headers=auth).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["message_count"] == 2


def test_follow_up_sends_previous_turns_to_the_model(client, auth, llm):
    llm.script = [{"content": "First answer"}, {"content": "Second answer"}]
    cid = say(client, auth, "my name is Ravi").json()["conversation"]["id"]
    say(client, auth, "what is my name?", conversation_id=cid)
    roles = [m["role"] for m in llm.last_messages()]
    contents = [m["content"] for m in llm.last_messages()]
    assert roles == ["system", "user", "assistant", "user"]
    assert "my name is Ravi" in contents[1] and contents[2] == "First answer"


def test_empty_and_oversized_messages_rejected(client, auth):
    assert say(client, auth, "   ").status_code == 400
    assert say(client, auth, "x" * 4001).status_code == 422
    assert client.post(f"{P}/chat", json={}, headers=auth).status_code == 400
    assert client.post(f"{P}/chat", json={"regenerate": True}, headers=auth).status_code == 400


# ------------------------------------------------------------------ language handling
def test_script_detection_switches_language_and_latin_keeps_it(client, auth, llm):
    llm.script = [{"content": "సరే"}, {"content": "సరే"}]
    r1 = say(client, auth, "నాకు రేషన్ కార్డ్ కావాలి").json()
    assert r1["language"] == "te" and r1["conversation"]["language"] == "te"
    assert "Telugu" in system_prompt(llm) and "native script" in system_prompt(llm)
    # romanised follow-up (code-mixed) must NOT flip the language back to English
    r2 = say(client, auth, "ration card documents enti?", conversation_id=r1["conversation"]["id"]).json()
    assert r2["language"] == "te"


def test_explicit_language_wins_over_detection(client, auth, llm):
    llm.script = [{"content": "ठीक है"}]
    r = say(client, auth, "నమస్కారం", language="hi").json()
    assert r["language"] == "hi"


def test_auto_detect_can_be_disabled(client, auth, llm):
    client.put(f"{P}/preferences", json={"auto_detect_language": False}, headers=auth)
    llm.script = [{"content": "ok"}]
    assert say(client, auth, "నాకు సహాయం కావాలి").json()["language"] == "en"


def test_marathi_conversation_is_not_flipped_to_hindi(client, auth, llm):
    llm.script = [{"content": "ठीक"}, {"content": "ठीक"}]
    cid = say(client, auth, "मला मदत हवी आहे", language="mr").json()["conversation"]["id"]
    assert say(client, auth, "मला रेशन कार्ड हवे", conversation_id=cid).json()["language"] == "mr"


def test_voice_input_is_recorded_and_voice_style_prompt_used(client, auth, llm):
    llm.script = [{"content": "Namaste"}]
    body = say(client, auth, "hello", input_mode="voice").json()
    assert body["user_message"]["input_mode"] == "voice"
    assert body["conversation"]["voice_message_count"] == 1
    assert "spoken aloud" in system_prompt(llm)


def test_set_language_tool_switches_conversation(client, auth, llm):
    llm.script = [{"tool_calls": [("set_language", {"language_code": "ta"})]}, {"content": "சரி"}]
    body = say(client, auth, "please speak in Tamil").json()
    assert body["language"] == "ta"
    assert client.get(f"{P}/conversations/{body['conversation']['id']}", headers=auth).json()["language"] == "ta"
    assert "Tamil" in system_prompt(llm)  # the follow-up LLM call already uses the new language


# ------------------------------------------------------------------ tool calling
def test_knowledge_base_tool_flow_marks_answer_as_tool_sourced(client, auth, llm):
    llm.script = [
        {"content": "Let me check.", "tool_calls": [("search_knowledge_base", {"query": "Ayushman card eligibility documents"})]},
        {"content": "You can check eligibility on the PM-JAY website."},
    ]
    body = say(client, auth, "How do I get an Ayushman card?").json()
    final = body["assistant_message"]
    assert final["source"] == "tool" and final["tools_used"] == ["search_knowledge_base"]

    interim = next(m for m in body["messages"] if m["tool_executions"])
    ex = interim["tool_executions"][0]
    assert ex["status"] == "success" and ex["tool_name"] == "search_knowledge_base" and ex["duration_ms"] is not None
    assert "Ayushman" in ex["summary"] and ex["result"]["results"][0]["title"].startswith("Ayushman")

    # the tool result reached the model with a proper assistant(tool_calls) -> tool pair
    history = llm.last_messages()
    assistant_tc = next(m for m in history if m["role"] == "assistant" and m.get("tool_calls"))
    tool_msg = next(m for m in history if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == assistant_tc["tool_calls"][0]["id"] and "5 lakh" in tool_msg["content"]
    # tool specs were offered; web_search was not (not configured)
    names = {t["function"]["name"] for t in llm.requests[0]["tools"]}
    assert "search_knowledge_base" in names and "web_search" not in names

    ex_list = client.get(f"{P}/agents/executions", headers=auth).json()
    assert ex_list["total"] == 1
    run = ex_list["items"][0]
    assert run["status"] == "completed" and run["intent"] == "search_knowledge_base" and run["steps"] == 2
    assert run["tool_executions"][0]["tool_name"] == "search_knowledge_base" and run["conversation_title"] == "Test Title"
    assert client.get(f"{P}/dashboard/summary", headers=auth).json()["tool_usage"] == [{"tool": "search_knowledge_base", "count": 1}]


def test_reloaded_conversation_still_shows_tool_cards(client, auth, llm):
    llm.script = [{"tool_calls": [("lookup_service_directory", {"category": "emergency", "query": "ambulance"})]}, {"content": "Call 108."}]
    cid = say(client, auth, "ambulance number?").json()["conversation"]["id"]
    detail = client.get(f"{P}/conversations/{cid}", headers=auth).json()
    cards = [e for m in detail["messages"] for e in m["tool_executions"]]
    assert len(cards) == 1 and cards[0]["result"]["results"][0]["phone"] == "108"
    assert detail["messages"][-1]["source"] == "tool"


def test_tool_failure_is_reported_to_model_and_conversation_continues(client, auth, llm):
    llm.script = [{"tool_calls": [("check_availability", {"provider_code": "NOPE-99"})]}, {"content": "I couldn't find that clinic; shall I search again?"}]
    body = say(client, auth, "free slots at NOPE-99").json()
    ex = next(e for m in body["messages"] for e in m["tool_executions"])
    assert ex["status"] == "error" and "No provider with code" in ex["error"]
    assert body["assistant_message"]["content"].startswith("I couldn't find")
    assert body["assistant_message"]["tools_used"] == []  # failed tools don't count as a source


def test_invalid_arguments_are_rejected_before_running(client, auth, llm):
    llm.script = [{"tool_calls": [("search_knowledge_base", {"top_k": 99})]}, {"content": "Sorry, let me rephrase."}]
    body = say(client, auth, "anything").json()
    ex = next(e for m in body["messages"] for e in m["tool_executions"])
    assert ex["status"] == "error" and "Invalid arguments" in ex["error"] and "query" in ex["error"]


def test_malformed_json_arguments_do_not_crash(client, auth, llm):
    llm.script = [{"tool_calls": [("search_knowledge_base", "{not json")]}, {"content": "ok"}]
    body = say(client, auth, "x").json()
    assert next(e for m in body["messages"] for e in m["tool_executions"])["status"] == "error"
    assert body["assistant_message"]["content"] == "ok"


def test_unknown_and_disabled_tools_cannot_be_called(client, auth, llm):
    llm.script = [{"tool_calls": [("run_shell", {"cmd": "rm -rf /"}), ("web_search", {"query": "news"})]}, {"content": "I can't do that."}]
    body = say(client, auth, "do bad things").json()
    execs = [e for m in body["messages"] for e in m["tool_executions"]]
    assert [e["status"] for e in execs] == ["error", "error"]
    assert all("Unknown or unavailable tool" in e["error"] for e in execs)


def test_web_search_enabled_when_configured(make_client, llm):
    c = make_client(tavily_api_key="tvly-test")
    h = login_guest(c)
    llm.script = [{"content": "ok"}]
    c.post(f"{P}/chat", json={"message": "hi"}, headers=h)
    assert "web_search" in {t["function"]["name"] for t in llm.requests[0]["tools"]}


def test_step_limit_stops_runaway_tool_loops(client, auth, llm):
    llm.script = [{"tool_calls": [("list_tasks", {})]} for _ in range(10)]
    body = say(client, auth, "loop forever").json()
    assert "could not finish" in body["assistant_message"]["content"]
    assert llm.streaming_calls == 4  # AGENT_MAX_STEPS in test settings


# ------------------------------------------------------------------ forms and tasks
def test_form_assistant_reports_missing_and_invalid_fields(client, auth, llm):
    llm.script = [
        {"tool_calls": [("form_assistant", {"form_id": "abha_creation_help", "fields": {"full_name": "Lakshmi", "mobile": "123"}})]},
        {"content": "What is your state and district?"},
    ]
    body = say(client, auth, "I want an ABHA ID").json()
    result = next(e for m in body["messages"] for e in m["tool_executions"])["result"]
    assert result["ready_to_submit"] is False and "mobile" in result["errors"]
    assert {m["field"] for m in result["missing"]} == {"state", "district", "mobile_linked_to_aadhaar"}


def test_task_tools_create_list_update(client, auth, llm):
    llm.script = [
        {"tool_calls": [("create_task", {"title": "Visit CSC", "due_date": "2999-02-01"})]}, {"content": "Task created."},
        {"tool_calls": [("list_tasks", {})]}, {"content": "You have 1 task."},
    ]
    r1 = say(client, auth, "remind me to visit the CSC").json()
    ref = next(e for m in r1["messages"] for e in m["tool_executions"])["result"]["reference"]
    assert ref.startswith("T-")
    tasks = client.get(f"{P}/tasks", headers=auth).json()
    assert tasks["total"] == 1 and tasks["items"][0]["title"] == "Visit CSC" and tasks["items"][0]["due_at"].startswith("2999-02-01")

    r = client.patch(f"{P}/tasks/{tasks['items'][0]['id']}", json={"status": "done"}, headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert client.get(f"{P}/tasks?status=done", headers=auth).json()["total"] == 1

    say(client, auth, "list my tasks", conversation_id=r1["conversation"]["id"])
    listed = [e for e in client.get(f"{P}/agents/executions", headers=auth).json()["items"][0]["tool_executions"]][0]["result"]
    assert listed["items"][0]["reference"] == ref and listed["items"][0]["status"] == "done"


def test_update_task_status_tool_is_scoped_to_the_owner(client, llm):
    alice, bob = login_guest(client), login_guest(client)
    llm.script = [{"tool_calls": [("create_task", {"title": "Alice only"})]}, {"content": "done"}]
    ref = next(e for m in say(client, alice, "make a task").json()["messages"] for e in m["tool_executions"])["result"]["reference"]
    llm.script = [{"tool_calls": [("update_task_status", {"reference": ref, "status": "cancelled"})]}, {"content": "no"}]
    body = say(client, bob, "cancel that task").json()
    assert next(e for m in body["messages"] for e in m["tool_executions"])["status"] == "error"
    assert client.get(f"{P}/tasks", headers=alice).json()["items"][0]["status"] == "open"


# ------------------------------------------------------------------ confirmation gate
def _pending(client, auth, llm, language=None):
    llm.script = [{"content": "I will submit your ABHA help request.", "tool_calls": [SUBMIT_CALL]}]
    r = say(client, auth, "yes please submit", **({"language": language} if language else {}))
    assert r.status_code == 200, r.text
    return r.json()


def test_sensitive_tool_waits_for_confirmation_and_does_not_run(client, auth, llm):
    body = _pending(client, auth, llm)
    pend = body["pending_confirmation"]
    assert pend["status"] == "awaiting_confirmation" and pend["requires_confirmation"] is True
    assert "Submit 'ABHA health ID assistance request'" in pend["explanation"] and "Lakshmi" in pend["explanation"]
    assert body["assistant_message"]["pending_confirmation"] is True
    assert body["assistant_message"]["content"] == "I will submit your ABHA help request."  # explained before acting
    assert client.get(f"{P}/tasks", headers=auth).json()["total"] == 0  # nothing happened yet
    run = client.get(f"{P}/agents/executions", headers=auth).json()["items"][0]
    assert run["status"] == "awaiting_confirmation"


def test_confirmation_without_model_text_still_gets_an_explanation(client, auth, llm):
    llm.script = [{"tool_calls": [SUBMIT_CALL]}]
    body = say(client, auth, "submit").json()
    assert "ready to do the following" in body["assistant_message"]["content"]


def test_approve_runs_tool_then_agent_finishes(client, auth, llm):
    pend = _pending(client, auth, llm)["pending_confirmation"]
    llm.script = [{"content": "Done! Your request is submitted."}]
    r = client.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": True}, headers=auth)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["assistant_message"]["content"] == "Done! Your request is submitted."
    assert out["assistant_message"]["source"] == "tool" and out["assistant_message"]["tools_used"] == ["submit_service_request"]
    assert out["pending_confirmation"] is None

    tasks = client.get(f"{P}/tasks", headers=auth).json()
    assert tasks["total"] == 1
    t = tasks["items"][0]
    assert t["kind"] == "service_request" and t["status"] == "submitted" and t["ref"].startswith("SR-")
    assert t["payload"]["fields"]["mobile"] == "9876543210" and t["payload"]["webhook"] == {"ok": False, "configured": False}
    # the model saw the reference number in the tool result
    tool_msg = next(m for m in reversed(llm.last_messages()) if m["role"] == "tool")
    assert t["ref"] in tool_msg["content"]

    run = client.get(f"{P}/agents/executions", headers=auth).json()["items"][0]
    assert run["status"] == "completed" and run["tool_executions"][0]["status"] == "success"


def test_deny_does_not_run_tool(client, auth, llm):
    pend = _pending(client, auth, llm)["pending_confirmation"]
    llm.script = [{"content": "Okay, I won't submit it."}]
    out = client.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": False}, headers=auth).json()
    assert out["assistant_message"]["content"] == "Okay, I won't submit it."
    assert out["assistant_message"]["tools_used"] == []
    assert client.get(f"{P}/tasks", headers=auth).json()["total"] == 0
    tool_msg = next(m for m in reversed(llm.last_messages()) if m["role"] == "tool")
    assert "declined" in tool_msg["content"]
    log = client.get(f"{P}/agents/executions", headers=auth).json()["items"][0]["tool_executions"][0]
    assert log["status"] == "denied"


def test_confirmation_cannot_be_replayed_or_used_by_others(client, auth, llm):
    pend = _pending(client, auth, llm)["pending_confirmation"]
    other = login_guest(client)
    r = client.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": True}, headers=other)
    assert r.status_code == 404
    llm.script = [{"content": "done"}]
    assert client.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": True}, headers=auth).status_code == 200
    replay = client.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": True}, headers=auth)
    assert replay.status_code == 400 and replay.json()["error"]["code"] == "not_awaiting_confirmation"
    assert client.get(f"{P}/tasks", headers=auth).json()["total"] == 1  # still only one submission


def test_moving_on_cancels_the_pending_action(client, auth, llm):
    body = _pending(client, auth, llm)
    cid, pend = body["conversation"]["id"], body["pending_confirmation"]
    llm.script = [{"content": "Sure, what else?"}]
    r = say(client, auth, "actually never mind, what is ABHA?", conversation_id=cid)
    assert r.status_code == 200
    log = client.get(f"{P}/agents/executions", headers=auth).json()["items"]
    statuses = {t["id"]: t["status"] for run in log for t in run["tool_executions"]}
    assert statuses[pend["id"]] == "cancelled"
    assert client.get(f"{P}/tasks", headers=auth).json()["total"] == 0
    # history sent to the model is still valid: every tool_call has a tool reply
    msgs = llm.last_messages()
    ids = [tc["id"] for m in msgs if m.get("tool_calls") for tc in m["tool_calls"]]
    replied = [m["tool_call_id"] for m in msgs if m["role"] == "tool"]
    assert ids and set(ids) <= set(replied)
    # and the stale confirmation can no longer be approved
    assert client.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": True}, headers=auth).status_code == 400


def test_invalid_form_data_is_caught_even_after_user_confirms(client, auth, llm):
    bad = ("submit_service_request", {"form_id": "abha_creation_help", "fields": {**ABHA_FIELDS, "mobile": "12345"}})
    llm.script = [{"content": "Submitting.", "tool_calls": [bad]}]
    pend = say(client, auth, "submit").json()["pending_confirmation"]
    llm.script = [{"content": "That mobile number looks wrong."}]
    client.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": True}, headers=auth)
    assert client.get(f"{P}/tasks", headers=auth).json()["total"] == 0
    log = client.get(f"{P}/agents/executions", headers=auth).json()["items"][0]["tool_executions"][0]
    assert log["status"] == "error" and "Form is not valid" in log["error"]


def test_second_sensitive_call_in_same_step_is_skipped_not_run(client, auth, llm):
    llm.script = [{"tool_calls": [SUBMIT_CALL, ("create_task", {"title": "after submit"})]}]
    body = say(client, auth, "do both").json()
    assert body["pending_confirmation"] and client.get(f"{P}/tasks", headers=auth).json()["total"] == 0
    llm.script = [{"content": "ok"}]
    client.post(f"{P}/agents/executions/{body['pending_confirmation']['id']}/confirm", json={"approve": False}, headers=auth)
    msgs = llm.last_messages()
    ids = [tc["id"] for m in msgs if m.get("tool_calls") for tc in m["tool_calls"]]
    assert set(ids) <= {m["tool_call_id"] for m in msgs if m["role"] == "tool"}


def test_webhook_receives_signed_submission(make_client, llm):
    import hashlib, hmac, json as _json

    import httpx

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"], seen["sig"], seen["event"] = request.content, request.headers.get("X-Signature"), request.headers.get("X-Event")
        return httpx.Response(200, json={"ok": True})

    from app.core.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient
    from tests.fakes import FakeBhashini

    app = create_app(
        Settings(_env_file=None, webhook_url="https://crm.test/hook", webhook_secret="s3cret"),
        llm_client=llm.client(), bhashini_client=FakeBhashini().client(), tools_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with TestClient(app) as c:
        h = login_guest(c)
        llm.script = [{"tool_calls": [SUBMIT_CALL]}]
        pend = c.post(f"{P}/chat", json={"message": "submit"}, headers=h).json()["pending_confirmation"]
        llm.script = [{"content": "done"}]
        c.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": True}, headers=h)
        task = c.get(f"{P}/tasks", headers=h).json()["items"][0]
    assert task["payload"]["webhook"]["ok"] is True
    assert seen["sig"] == hmac.new(b"s3cret", seen["body"], hashlib.sha256).hexdigest()
    payload = _json.loads(seen["body"])
    assert seen["event"] == "service_request.submitted" and payload["event"] == "service_request.submitted"
    assert payload["data"]["reference"] == task["ref"]


# ------------------------------------------------------------------ regenerate & memory
def test_regenerate_replaces_last_answer(client, auth, llm):
    llm.script = [{"content": "First try"}]
    cid = say(client, auth, "tell me something").json()["conversation"]["id"]
    llm.script = [{"content": "Second try"}]
    r = client.post(f"{P}/chat", json={"conversation_id": cid, "regenerate": True}, headers=auth)
    assert r.status_code == 200 and r.json()["assistant_message"]["content"] == "Second try"
    detail = client.get(f"{P}/conversations/{cid}", headers=auth).json()
    assert [(m["role"], m["content"]) for m in detail["messages"]] == [("user", "tell me something"), ("assistant", "Second try")]
    assert detail["message_count"] == 2


def test_rolling_summary_is_created_and_used(make_client, llm):
    c = make_client(summary_trigger_messages=12)  # the newest 10 messages always stay verbatim
    h = login_guest(c)
    llm.title = "Summary text"
    llm.script = [{"content": f"answer {i}"} for i in range(9)]
    cid = None
    for i in range(7):
        body = c.post(f"{P}/chat", json={"message": f"question {i}", "conversation_id": cid}, headers=h).json()
        cid = body["conversation"]["id"]
    assert body["conversation"]["summary"] == "Summary text"
    c.post(f"{P}/chat", json={"message": "one more", "conversation_id": cid}, headers=h)
    assert "Summary of the earlier part" in system_prompt(llm) and "Summary text" in system_prompt(llm)


# ------------------------------------------------------------------ failures
@pytest.fixture
def no_sleep(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr("app.services.llm_service.asyncio.sleep", instant)


def test_llm_outage_returns_502_and_keeps_user_message_for_retry(client, auth, llm, no_sleep):
    llm.script = [{"error": 500}] * 3
    r = say(client, auth, "hello?")
    assert r.status_code == 502 and r.json()["error"]["code"] == "llm_error"
    assert llm.streaming_calls == 3  # retried
    cid = client.get(f"{P}/conversations", headers=auth).json()["items"][0]["id"]
    detail = client.get(f"{P}/conversations/{cid}", headers=auth).json()
    assert [m["role"] for m in detail["messages"]] == ["user"]  # message kept
    run = client.get(f"{P}/agents/executions", headers=auth).json()["items"][0]
    assert run["status"] == "failed" and "llm_error" in run["error"]

    llm.script = [{"content": "Back online"}]  # retry via regenerate
    r = client.post(f"{P}/chat", json={"conversation_id": cid, "regenerate": True}, headers=auth)
    assert r.status_code == 200 and r.json()["assistant_message"]["content"] == "Back online"


def test_llm_auth_failure_is_not_retried(client, auth, llm, no_sleep):
    llm.script = [{"error": 401}]
    r = say(client, auth, "hi")
    assert r.status_code == 502 and r.json()["error"]["code"] == "llm_auth_failed" and llm.streaming_calls == 1


def test_llm_rate_limit_is_retried_then_succeeds(client, auth, llm, no_sleep):
    llm.script = [{"error": 429}, {"content": "worked"}]
    assert say(client, auth, "hi").json()["assistant_message"]["content"] == "worked"


def test_malformed_tool_call_falls_back_to_plain_answer(client, auth, llm, no_sleep):
    llm.script = [{"error": 400, "body": '{"error":{"message":"Failed to call a function. tool_use_failed"}}'}, {"content": "Plain answer"}]
    r = say(client, auth, "hi")
    assert r.json()["assistant_message"]["content"] == "Plain answer"
    streaming = [q for q in llm.requests if q.get("stream")]
    assert "tools" in streaming[0] and "tools" not in streaming[1]


def test_llm_not_configured_gives_actionable_503(make_client):
    c = make_client(llm_api_key="")
    h = login_guest(c)
    r = c.post(f"{P}/chat", json={"message": "hi"}, headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_not_configured"
    assert "LLM_API_KEY" in r.json()["error"]["message"]
    assert c.get(f"{P}/health", headers=h).json()["llm_configured"] is False


def test_empty_model_reply_gets_fallback_text(make_client, llm, monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr("app.services.llm_service.asyncio.sleep", instant)
    c = make_client(response_validation_enabled=False)  # with the response check on, an empty reply gets a rewrite or a safe fallback (test_response_validation.py)
    llm.script = [{"content": ""}] * 3  # an empty answer is retried before the user sees the apology
    assert "could not come up with an answer" in say(c, login_guest(c), "hi").json()["assistant_message"]["content"]


# ------------------------------------------------------------------ websocket streaming
def _collect(ws, until=("done", "error", "cancelled")):
    events = []
    while True:
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] in until:
            return events


def _ws(client, auth):
    token = auth["Authorization"].split()[1]
    return client.websocket_connect(f"{P}/ws/chat?token={token}")


def test_websocket_streams_tokens_in_order(client, auth, llm):
    llm.script = [{"content": "Hello there friend"}]
    with _ws(client, auth) as ws:
        ws.send_json({"type": "message", "text": "hi"})
        events = _collect(ws)
    kinds = [e["type"] for e in events]
    assert kinds[:3] == ["conversation", "language", "user_message"]
    assert "stage" in kinds and kinds.count("token") >= 2
    assert "".join(e["delta"] for e in events if e["type"] == "token") == "Hello there friend"
    assert kinds.index("message") > max(i for i, k in enumerate(kinds) if k == "token")
    assert kinds[-1] == "done" and events[-1]["status"] == "completed"
    final = next(e for e in events if e["type"] == "message")["message"]
    assert final["content"] == "Hello there friend"
    conv_events = [e for e in events if e["type"] == "conversation"]
    assert conv_events[-1]["conversation"]["title"] == "Test Title"  # title arrives after the answer


def test_websocket_tool_events_and_confirmation_roundtrip(client, auth, llm):
    llm.script = [
        {"content": "Checking.", "tool_calls": [("lookup_service_directory", {"category": "emergency"})]},
        {"content": "Here are the numbers."},
    ]
    with _ws(client, auth) as ws:
        ws.send_json({"type": "message", "text": "emergency numbers?"})
        events = _collect(ws)
        kinds = [e["type"] for e in events]
        assert "tool_start" in kinds and "tool_result" in kinds
        assert kinds.index("tool_start") < kinds.index("tool_result") < len(kinds) - 1
        result = next(e for e in events if e["type"] == "tool_result")["tool_execution"]
        assert result["status"] == "success" and result["tool_name"] == "lookup_service_directory"

        llm.script = [{"content": "Submitting.", "tool_calls": [SUBMIT_CALL]}]
        ws.send_json({"type": "message", "text": "submit my ABHA request", "conversation_id": events[0]["conversation"]["id"]})
        events = _collect(ws)
        pend = next(e for e in events if e["type"] == "confirmation_required")["tool_execution"]
        assert events[-1]["type"] == "done" and events[-1]["status"] == "awaiting_confirmation"

        llm.script = [{"content": "All done."}]
        ws.send_json({"type": "confirm", "execution_id": pend["id"], "approve": True})
        events = _collect(ws)
        kinds = [e["type"] for e in events]
        assert "tool_start" in kinds and "tool_result" in kinds and events[-1]["status"] == "completed"
        assert next(e for e in events if e["type"] == "message")["message"]["content"] == "All done."
    assert client.get(f"{P}/tasks", headers=auth).json()["total"] == 1


def test_websocket_regenerate_ping_and_bad_input(client, auth, llm):
    llm.script = [{"content": "one"}, {"content": "two"}]
    with _ws(client, auth) as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.send_json({"type": "bogus"})
        assert ws.receive_json()["code"] == "invalid_message"
    # regenerate without a conversation id is a validation error, not a crash
    with _ws(client, auth) as ws:
        ws.send_json({"type": "regenerate"})
        ev = _collect(ws)[-1]
        assert ev["type"] == "error" and ev["code"] == "bad_request"
        ws.send_json({"type": "message", "text": "hello"})
        events = _collect(ws)
        cid = events[0]["conversation"]["id"]
        ws.send_json({"type": "regenerate", "conversation_id": cid})
        events = _collect(ws)
        assert next(e for e in events if e["type"] == "message")["message"]["content"] == "two"


def test_websocket_rejects_missing_or_bad_token(client):
    for url in (f"{P}/ws/chat", f"{P}/ws/chat?token=garbage"):
        with client.websocket_connect(url) as ws:
            ev = ws.receive_json()
            assert ev["type"] == "error" and ev["code"] == "unauthorized"


def test_websocket_reports_llm_errors_as_events(client, auth, llm, no_sleep):
    llm.script = [{"error": 401}]
    with _ws(client, auth) as ws:
        ws.send_json({"type": "message", "text": "hi"})
        ev = _collect(ws)[-1]
    assert ev["type"] == "error" and ev["code"] == "llm_auth_failed" and ev["retryable"] is False

