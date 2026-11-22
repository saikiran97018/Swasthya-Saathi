"""Saathi Plus (Razorpay subscriptions): plans, checkout verification, webhooks, cancellation and the free plan's daily limits."""
import hashlib
import hmac
import json
import time

import httpx
import pytest

from app.database.models import Conversation
from app.services.billing import PlanLimitReached, check_call_allowed
from tests.test_healthcare import new_user, run

P = "/api/v1"
KEY_ID, KEY_SECRET, WH_SECRET = "rzp_test_abc123", "test_secret_not_real", "whsec_not_real"
ENV = dict(razorpay_key_id=KEY_ID, razorpay_key_secret=KEY_SECRET, razorpay_webhook_secret=WH_SECRET, razorpay_plan_monthly="plan_M1", razorpay_plan_yearly="plan_Y1")


def sign(secret: str, text: str | bytes) -> str:
    return hmac.new(secret.encode(), text if isinstance(text, bytes) else text.encode(), hashlib.sha256).hexdigest()


class Razorpay:
    """Stands in for api.razorpay.com."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None, str]] = []
        self.state = {"status": "created", "current_end": None, "paid_count": 0}
        self.fail = False
        self.n = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body, request.headers.get("authorization", "")))
        if self.fail:
            return httpx.Response(500, json={"error": {"description": "boom"}})
        path = request.url.path
        if request.method == "POST" and path == "/v1/subscriptions":
            self.n += 1
            return httpx.Response(200, json={"id": f"sub_T{self.n}", "status": "created", "plan_id": body["plan_id"]})
        if request.method == "GET" and path.startswith("/v1/subscriptions/"):
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[1], **self.state})
        if request.method == "POST" and path.endswith("/cancel"):
            return httpx.Response(200, json={"id": path.split("/")[3], "status": "active", "has_scheduled_changes": True})
        return httpx.Response(404, json={"error": {"description": "unexpected"}})

    def attach(self, client) -> "Razorpay":
        client.app.state.billing.http = httpx.AsyncClient(transport=httpx.MockTransport(self))
        return self


@pytest.fixture
def shop(make_client):
    c = make_client(**ENV)
    return c, Razorpay().attach(c)


def future(days=30) -> int:
    return int(time.time()) + days * 86400


def start(c, auth, plan="monthly"):
    r = c.post(f"{P}/billing/subscribe", json={"plan": plan}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def checkout(c, auth, sub_id, payment="pay_ABC123", secret=KEY_SECRET):
    return c.post(f"{P}/billing/verify", json={"razorpay_payment_id": payment, "razorpay_subscription_id": sub_id, "razorpay_signature": sign(secret, f"{payment}|{sub_id}")}, headers=auth)


def hook(c, event, sub_id, event_id="evt_1", secret=WH_SECRET, **entity):
    body = json.dumps({"event": event, "payload": {"subscription": {"entity": {"id": sub_id, **entity}}, "payment": {"entity": {"id": "pay_W1"}}}}).encode()
    return c.post(f"{P}/billing/webhook", content=body, headers={"x-razorpay-signature": sign(secret, body), "x-razorpay-event-id": event_id, "content-type": "application/json"})


def status(c, auth):
    return c.get(f"{P}/billing/status", headers=auth).json()


# ------------------------------------------------------------------------------------------------ plans
def test_without_keys_payments_are_off_and_nothing_is_limited(client):
    auth, _ = new_user(client)
    plans = client.get(f"{P}/billing/plans", headers=auth).json()
    assert plans["enabled"] is False and plans["plans"] == [] and plans["key_id"] is None
    assert status(client, auth)["messages_limit"] is None
    assert client.post(f"{P}/billing/subscribe", json={"plan": "monthly"}, headers=auth).status_code == 503


def test_plans_list_prices_and_the_public_key_only(shop):
    c, _ = shop
    auth, _ = new_user(c)
    plans = c.get(f"{P}/billing/plans", headers=auth).json()
    assert plans["enabled"] and plans["key_id"] == KEY_ID and [p["id"] for p in plans["plans"]] == ["monthly", "yearly"]
    assert KEY_SECRET not in json.dumps(plans) and WH_SECRET not in json.dumps(plans)
    assert plans["plans"][1]["note"] == "Save ₹189"


def test_requires_login(shop):
    c, _ = shop
    for method, path in (("get", "/billing/plans"), ("get", "/billing/status"), ("post", "/billing/subscribe"), ("post", "/billing/verify"), ("post", "/billing/cancel")):
        assert getattr(c, method)(f"{P}{path}").status_code == 401, path


# ------------------------------------------------------------------------------------------------ subscribe + verify
def test_subscribe_creates_the_subscription_at_razorpay(shop):
    c, rz = shop
    auth, uid = new_user(c)
    out = start(c, auth, "yearly")
    assert out == {"subscription_id": "sub_T1", "key_id": KEY_ID, "plan": "yearly"}
    method, path, body, authz = rz.calls[0]
    assert (method, path) == ("POST", "/v1/subscriptions") and body["plan_id"] == "plan_Y1" and body["total_count"] == 10 and body["notes"]["user_id"] == uid
    assert authz.startswith("Basic ")
    assert status(c, auth)["plan"] == "free"  # nothing is paid yet


def test_a_razorpay_failure_is_reported_without_leaking_details(shop):
    c, rz = shop
    rz.fail = True
    auth, _ = new_user(c)
    r = c.post(f"{P}/billing/subscribe", json={"plan": "monthly"}, headers=auth)
    assert r.status_code == 502 and "boom" not in r.text and KEY_SECRET not in r.text


def test_checkout_with_a_good_signature_turns_plus_on(shop):
    c, rz = shop
    auth, _ = new_user(c)
    sid = start(c, auth)["subscription_id"]
    rz.state.update(status="active", current_end=future(), paid_count=1)
    out = checkout(c, auth, sid).json()
    assert out["plan"] == "plus" and out["status"] == "active" and out["messages_limit"] is None and out["billing_period"] == "monthly"
    assert out["renews_at"] is not None


def test_checkout_with_a_bad_signature_changes_nothing(shop):
    c, rz = shop
    auth, _ = new_user(c)
    sid = start(c, auth)["subscription_id"]
    r = checkout(c, auth, sid, secret="someone-elses-secret")
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_signature"
    assert status(c, auth)["plan"] == "free"


def test_checkout_still_works_if_razorpay_cannot_be_reached_afterwards(shop):
    c, rz = shop
    auth, _ = new_user(c)
    sid = start(c, auth)["subscription_id"]
    rz.fail = True  # the signature already proves the payment; the webhook completes the picture
    out = checkout(c, auth, sid).json()
    assert out["plan"] == "plus" and out["status"] == "active"


def test_you_cannot_claim_someone_elses_subscription(shop):
    c, rz = shop
    a, _ = new_user(c)
    b, _ = new_user(c)
    sid = start(c, a)["subscription_id"]
    assert checkout(c, b, sid).status_code == 404
    assert status(c, b)["plan"] == "free"


def test_cannot_subscribe_twice(shop):
    c, rz = shop
    auth, _ = new_user(c)
    sid = start(c, auth)["subscription_id"]
    rz.state.update(status="active", current_end=future(), paid_count=1)
    checkout(c, auth, sid)
    r = c.post(f"{P}/billing/subscribe", json={"plan": "monthly"}, headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_subscribed"


# ------------------------------------------------------------------------------------------------ webhook
def test_webhook_rejects_a_wrong_signature(shop):
    c, _ = shop
    assert hook(c, "subscription.activated", "sub_X", secret="wrong").status_code == 400
    assert c.post(f"{P}/billing/webhook", content=b"{}").status_code == 400


def test_webhook_without_a_configured_secret_rejects_everything(make_client):
    c = make_client(**{**ENV, "razorpay_webhook_secret": ""})
    assert hook(c, "subscription.activated", "sub_X", secret="").status_code == 400


def test_webhook_activation_and_renewal(shop):
    c, rz = shop
    auth, _ = new_user(c)
    sid = start(c, auth)["subscription_id"]
    r = hook(c, "subscription.activated", sid, event_id="e1", status="active", current_end=future(30), paid_count=1)
    assert r.status_code == 200 and r.json() == {"status": "applied"}
    assert status(c, auth)["plan"] == "plus"
    hook(c, "subscription.charged", sid, event_id="e2", status="active", current_end=future(60), paid_count=2)
    assert status(c, auth)["plan"] == "plus"


def test_each_webhook_event_is_applied_once(shop):
    c, _ = shop
    auth, _ = new_user(c)
    sid = start(c, auth)["subscription_id"]
    assert hook(c, "subscription.activated", sid, event_id="same", status="active", current_end=future(), paid_count=1).json()["status"] == "applied"
    assert hook(c, "subscription.halted", sid, event_id="same", status="halted").json()["status"] == "duplicate"  # a retry: ignored
    assert status(c, auth)["plan"] == "plus"


def test_cancelled_keeps_plus_until_the_paid_period_ends(shop):
    c, _ = shop
    auth, _ = new_user(c)
    sid = start(c, auth)["subscription_id"]
    hook(c, "subscription.activated", sid, event_id="a", status="active", current_end=future(10), paid_count=1)
    hook(c, "subscription.cancelled", sid, event_id="b", status="cancelled", current_end=future(10), paid_count=1)
    s = status(c, auth)
    assert s["plan"] == "plus" and s["cancel_at_cycle_end"] is True  # still paid for


def test_an_expired_or_halted_subscription_is_the_free_plan(shop):
    c, _ = shop
    auth, _ = new_user(c)
    sid = start(c, auth)["subscription_id"]
    hook(c, "subscription.activated", sid, event_id="a", status="active", current_end=future(10), paid_count=1)
    hook(c, "subscription.cancelled", sid, event_id="b", status="cancelled", current_end=int(time.time()) - 3600, paid_count=1)
    assert status(c, auth)["plan"] == "free"
    other, _ = new_user(c)
    sid2 = start(c, other)["subscription_id"]
    hook(c, "subscription.halted", sid2, event_id="c", status="halted")  # never paid: no access
    assert status(c, other)["plan"] == "free"


def test_events_for_unknown_subscriptions_are_ignored(shop):
    c, _ = shop
    assert hook(c, "subscription.activated", "sub_NOT_OURS", status="active").json() == {"status": "ignored"}


# ------------------------------------------------------------------------------------------------ cancel
def test_cancel_stops_renewal_at_the_end_of_the_period(shop):
    c, rz = shop
    auth, _ = new_user(c)
    sid = start(c, auth)["subscription_id"]
    rz.state.update(status="active", current_end=future(), paid_count=1)
    checkout(c, auth, sid)
    out = c.post(f"{P}/billing/cancel", headers=auth).json()
    assert out["plan"] == "plus" and out["cancel_at_cycle_end"] is True
    method, path, body, _ = rz.calls[-1]
    assert path == f"/v1/subscriptions/{sid}/cancel" and body == {"cancel_at_cycle_end": 1}


def test_cancel_without_a_subscription_is_a_clear_error(shop):
    c, _ = shop
    auth, _ = new_user(c)
    r = c.post(f"{P}/billing/cancel", headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "nothing_to_cancel"


# ------------------------------------------------------------------------------------------------ free plan limits
def chat(c, auth, text="hello"):
    return c.post(f"{P}/chat", json={"message": text}, headers=auth)


def test_free_plan_has_a_daily_message_limit_but_plus_does_not(make_client):
    c = make_client(**ENV, free_daily_messages=2)
    rz = Razorpay().attach(c)
    auth, _ = new_user(c)
    assert chat(c, auth).status_code == 200 and chat(c, auth).status_code == 200
    r = chat(c, auth)
    assert r.status_code == 402 and r.json()["error"]["code"] == "plan_limit" and "112" in r.json()["error"]["message"]
    assert status(c, auth)["messages_today"] == 2 and status(c, auth)["messages_limit"] == 2
    sid = start(c, auth)["subscription_id"]
    hook(c, "subscription.activated", sid, status="active", current_end=future(), paid_count=1)
    assert chat(c, auth).status_code == 200  # Plus: no limit


def test_limits_are_off_until_payments_are_set_up(make_client):
    c = make_client(free_daily_messages=1)  # no Razorpay keys
    auth, _ = new_user(c)
    assert all(chat(c, auth).status_code == 200 for _ in range(3))


def test_limits_are_per_person(make_client):
    c = make_client(**ENV, free_daily_messages=1)
    a, _ = new_user(c)
    b, _ = new_user(c)
    assert chat(c, a).status_code == 200 and chat(c, a).status_code == 402
    assert chat(c, b).status_code == 200


def test_live_call_limit(make_client):
    c = make_client(**ENV, free_daily_calls=1)
    auth, uid = new_user(c)
    settings = c.app.state.settings

    async def attempt(session):
        from app.database.models import User
        user = await session.get(User, __import__("uuid").UUID(uid))
        await check_call_allowed(session, settings, user)  # first call is fine
        session.add(Conversation(user_id=user.id, title="Live call", language="en"))
        await session.flush()
        try:
            await check_call_allowed(session, settings, user)
        except PlanLimitReached as exc:
            return str(exc)
        return None

    assert "free live calls" in (run(c, attempt) or "")


def test_security_headers_are_on_every_response(client):
    r = client.get(f"{P}/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "microphone=(self)" in r.headers["permissions-policy"] and "strict-transport-security" not in r.headers  # plain http: no HSTS
    secure = client.get(f"{P}/health", headers={"x-forwarded-proto": "https"})
    assert secure.headers["strict-transport-security"].startswith("max-age=")
