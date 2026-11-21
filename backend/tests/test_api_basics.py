"""Health, auth, conversations, preferences, tasks, dashboard."""
from tests.conftest import login_guest

P = "/api/v1"


def test_health_reports_dependencies(client):
    r = client.get(f"{P}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["database"] is True
    assert body["bhashini_configured"] and body["llm_configured"] and body["llm_model"] == "test-model"
    assert body["web_search_configured"] is False


def test_protected_routes_require_token(client):
    for method, path in [("get", "/conversations"), ("post", "/chat"), ("get", "/agents"), ("get", "/preferences"), ("get", "/tasks"), ("get", "/dashboard/summary")]:
        r = getattr(client, method)(P + path)
        assert r.status_code == 401, (path, r.status_code)
        assert r.json()["error"]["code"] == "unauthorized"
    assert client.get(f"{P}/conversations", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_register_login_and_guest_upgrade(client):
    guest = login_guest(client, "Asha")
    me = client.get(f"{P}/auth/me", headers=guest).json()
    assert me["is_guest"] is True and me["display_name"] == "Asha"

    # make a conversation as guest, then upgrade: it must survive
    conv = client.post(f"{P}/conversations", json={"title": "Keep me"}, headers=guest).json()
    up = client.post(f"{P}/auth/upgrade", json={"email": "Asha@Example.com", "password": "supersecret1"}, headers=guest)
    assert up.status_code == 200 and up.json()["user"]["is_guest"] is False

    login = client.post(f"{P}/auth/login", json={"email": "asha@example.com", "password": "supersecret1"})
    assert login.status_code == 200
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert [c["id"] for c in client.get(f"{P}/conversations", headers=h).json()["items"]] == [conv["id"]]

    bad = client.post(f"{P}/auth/login", json={"email": "asha@example.com", "password": "wrongpass"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
    unknown = client.post(f"{P}/auth/login", json={"email": "nobody@example.com", "password": "wrongpass"})
    assert unknown.json()["error"]["message"] == bad.json()["error"]["message"]  # no account enumeration

    dup = client.post(f"{P}/auth/register", json={"email": "asha@example.com", "password": "anotherpass1"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "email_taken"


def test_register_validates_input(client):
    r = client.post(f"{P}/auth/register", json={"email": "not-an-email", "password": "short"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error" and {d["field"] for d in err["details"]} == {"email", "password"}


def test_conversation_crud_search_and_pagination(client, auth):
    a = client.post(f"{P}/conversations", json={"title": "Farming loans", "language": "te"}, headers=auth).json()
    b = client.post(f"{P}/conversations", headers=auth).json()
    assert a["language"] == "te" and b["title"] == "New conversation" and b["language"] == "en"

    listing = client.get(f"{P}/conversations", headers=auth).json()
    assert listing["total"] == 2 and listing["items"][0]["id"] == b["id"]  # newest first

    assert client.get(f"{P}/conversations?q=farming", headers=auth).json()["total"] == 1
    assert client.get(f"{P}/conversations?q=100%25", headers=auth).json()["total"] == 0  # % is escaped, not a wildcard
    assert len(client.get(f"{P}/conversations?limit=1", headers=auth).json()["items"]) == 1

    renamed = client.patch(f"{P}/conversations/{a['id']}", json={"title": "Crop insurance"}, headers=auth)
    assert renamed.status_code == 200 and renamed.json()["title"] == "Crop insurance"
    detail = client.get(f"{P}/conversations/{a['id']}", headers=auth).json()
    assert detail["title"] == "Crop insurance" and detail["messages"] == []

    assert client.delete(f"{P}/conversations/{a['id']}", headers=auth).status_code == 204
    assert client.get(f"{P}/conversations/{a['id']}", headers=auth).status_code == 404


def test_users_cannot_access_each_others_conversations(client):
    alice, bob = login_guest(client), login_guest(client)
    conv = client.post(f"{P}/conversations", json={"title": "Private"}, headers=alice).json()
    for call in (
        lambda: client.get(f"{P}/conversations/{conv['id']}", headers=bob),
        lambda: client.patch(f"{P}/conversations/{conv['id']}", json={"title": "x"}, headers=bob),
        lambda: client.delete(f"{P}/conversations/{conv['id']}", headers=bob),
        lambda: client.post(f"{P}/chat", json={"conversation_id": conv["id"], "message": "hi"}, headers=bob),
    ):
        r = call()
        assert r.status_code == 404 and r.json()["error"]["code"] == "conversation_not_found"
    assert client.get(f"{P}/conversations", headers=bob).json()["total"] == 0


def test_languages_and_preferences(client, auth):
    langs = client.get(f"{P}/languages").json()
    codes = {l["code"] for l in langs}
    assert {"en", "hi", "te", "ta", "kn", "ml", "bn"} <= codes
    assert next(l for l in langs if l["code"] == "te")["tts"] is True

    prefs = client.get(f"{P}/preferences", headers=auth).json()
    assert prefs["primary_language"] == "en" and prefs["auto_detect_language"] is True
    assert prefs["auto_send_voice"] is True  # speaking is enough: no manual Send tap unless the person turns this off
    assert client.put(f"{P}/preferences", json={"auto_send_voice": False}, headers=auth).json()["auto_send_voice"] is False
    assert client.put(f"{P}/preferences", json={"auto_send_voice": True}, headers=auth).json()["auto_send_voice"] is True

    r = client.put(
        f"{P}/preferences",
        json={"primary_language": "te", "secondary_languages": ["hi", "en", "te"], "tts_gender": "male", "theme": "dark", "silence_timeout_ms": 2000},
        headers=auth,
    )
    assert r.status_code == 200
    out = r.json()
    assert out["primary_language"] == "te" and sorted(out["secondary_languages"]) == ["en", "hi"]  # primary not duplicated
    assert out["tts_gender"] == "male" and out["theme"] == "dark"

    # new conversations default to the user's primary language
    assert client.post(f"{P}/conversations", headers=auth).json()["language"] == "te"
    assert client.put(f"{P}/preferences", json={"primary_language": "xx"}, headers=auth).status_code == 400
    assert client.put(f"{P}/preferences", json={"silence_timeout_ms": 10}, headers=auth).status_code == 422


def test_agents_listing_hides_nothing_but_marks_disabled_and_sensitive(client, auth):
    agents = client.get(f"{P}/agents", headers=auth).json()
    tools = {t["name"]: t for t in agents[0]["tools"]}
    assert tools["submit_service_request"]["requires_confirmation"] is True
    assert tools["web_search"]["enabled"] is False  # no search key configured
    assert tools["search_knowledge_base"]["enabled"] is True
    assert agents[0]["model"] == "test-model"


def test_dashboard_summary_empty(client, auth):
    d = client.get(f"{P}/dashboard/summary", headers=auth).json()
    assert d["conversations"] == 0 and d["messages"] == 0 and d["tool_runs"] == 0 and d["tool_usage"] == []


def test_task_not_found_and_validation(client, auth):
    import uuid

    assert client.patch(f"{P}/tasks/{uuid.uuid4()}", json={"status": "done"}, headers=auth).status_code == 404
    assert client.get(f"{P}/tasks?status=bogus", headers=auth).status_code == 422


def test_rate_limit_returns_429_with_retry_after(make_client):
    c = make_client(rate_limit_per_minute=5)
    h = login_guest(c)  # 1 request
    codes = [c.get(f"{P}/conversations", headers=h).status_code for _ in range(8)]
    assert codes.count(429) >= 3
    r = c.get(f"{P}/conversations", headers=h)
    assert r.status_code == 429 and "retry-after" in r.headers and r.json()["error"]["code"] == "rate_limited"
    assert c.get(f"{P}/health").status_code == 200  # health is exempt


def test_cors_allows_configured_origin_only(client):
    ok = client.options(f"{P}/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options(f"{P}/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers
