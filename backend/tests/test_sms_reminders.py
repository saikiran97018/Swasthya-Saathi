"""Text-message reminders: opt-in, one text per due reminder, never blocks the in-app reminder, never leaks the keys."""
from datetime import timedelta

import httpx
import pytest

from app.services.sms import SmsService, shorten, to_e164
from tests.test_booking_api import book
from tests.test_healthcare import appointments, first_slot, new_user, when

P = "/api/v1"
SID, TOKEN = "ACtest0000000000000000000000000000", "test-auth-token-not-real"
SMS_ENV = dict(twilio_account_sid=SID, twilio_auth_token=TOKEN, sms_from="+15550001111")


class Twilio:
    """Stands in for api.twilio.com and remembers what was sent."""

    def __init__(self, status: int = 201, body: dict | None = None):
        self.sent: list[dict] = []
        self.requests: list[httpx.Request] = []
        self.status, self.body = status, body or {"sid": "SM1"}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.sent.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(self.status, json=self.body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


def wire(client, twilio: Twilio) -> None:
    client.app.state.reminder_service.sms.http = twilio.client()


def book_visit(client):
    auth, _ = new_user(client)
    r = book(client, auth, first_slot(client, auth, days_ahead=3))
    assert r.status_code == 201, r.text
    return auth, r.json()


def deliver_all(client, auth):
    """Run the reminder loop a minute before the visit: both appointment reminders are due, the feedback prompt is not yet."""
    start = max(when(a) for a in appointments(client, auth))
    return client.portal.call(client.app.state.reminder_service.deliver_due, start - timedelta(minutes=1))


# ------------------------------------------------------------------------------------------------ helpers
@pytest.mark.parametrize("raw,expected", [
    ("9876543210", "+919876543210"), ("98765 43210", "+919876543210"), ("09876543210", "+919876543210"),
    ("919876543210", "+919876543210"), ("+919876543210", "+919876543210"), ("+14155550123", "+14155550123"),
    ("12345", None), ("", None), ("+12", None), ("abcdefghij", None),
])
def test_phone_numbers_are_made_international(raw, expected):
    assert to_e164(raw) == expected


def test_long_text_is_shortened_without_breaking_words_into_whitespace():
    assert shorten("a  b\nc", 50) == "a b c"
    out = shorten("word " * 100, 40)
    assert len(out) <= 40 and out.endswith("…")


def test_twilio_request_shape_and_credentials(make_client):
    c = make_client(**SMS_ENV)
    t = Twilio()
    svc = SmsService(c.app.state.settings, t.client())
    result = c.portal.call(svc.send, "9876543210", "hello there")
    assert result.ok
    req = t.requests[0]
    assert str(req.url) == f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json"
    assert t.sent[0] == {"To": "+919876543210", "From": "+15550001111", "Body": "hello there"}
    assert req.headers["authorization"].startswith("Basic ")


def test_messaging_service_id_is_used_when_given(make_client):
    c = make_client(twilio_account_sid=SID, twilio_auth_token=TOKEN, sms_from="MG123")
    t = Twilio()
    c.portal.call(SmsService(c.app.state.settings, t.client()).send, "9876543210", "hi")
    assert t.sent[0].get("MessagingServiceSid") == "MG123" and "From" not in t.sent[0]


def test_failures_report_a_short_reason_and_never_the_keys(make_client, caplog):
    c = make_client(**SMS_ENV)
    t = Twilio(status=400, body={"code": 21211, "message": f"bad number for {SID}"})
    with caplog.at_level("DEBUG"):
        result = c.portal.call(SmsService(c.app.state.settings, t.client()).send, "9876543210", "hi")
    assert not result.ok and result.detail == "twilio_21211"
    assert TOKEN not in caplog.text and SID not in caplog.text
    assert c.portal.call(SmsService(c.app.state.settings, t.client()).send, "12345", "hi").detail == "invalid_number"


def test_not_configured_sends_nothing(client):
    t = Twilio()
    result = client.portal.call(SmsService(client.app.state.settings, t.client()).send, "9876543210", "hi")
    assert not result.ok and result.detail == "sms_not_configured" and not t.requests


# ------------------------------------------------------------------------------------------------ settings
def test_preference_defaults_off_and_says_whether_the_server_can_text(make_client):
    off = make_client()
    auth, _ = new_user(off)
    prefs = off.get(f"{P}/preferences", headers=auth).json()
    assert prefs["sms_reminders"] is False and prefs["sms_available"] is False

    on = make_client(**SMS_ENV)
    auth, _ = new_user(on)
    assert on.get(f"{P}/preferences", headers=auth).json()["sms_available"] is True
    assert on.put(f"{P}/preferences", json={"sms_reminders": True}, headers=auth).json()["sms_reminders"] is True
    assert on.put(f"{P}/preferences", json={"sms_reminders": False}, headers=auth).json()["sms_reminders"] is False


# ------------------------------------------------------------------------------------------------ delivery
def test_opted_in_person_gets_a_text_for_each_appointment_reminder(make_client):
    c = make_client(**SMS_ENV)
    t = Twilio()
    wire(c, t)
    auth, appt = book_visit(c)
    c.put(f"{P}/preferences", json={"sms_reminders": True}, headers=auth)
    deliver_all(c, auth)
    assert len(t.sent) == 2  # the two appointment reminders
    for m in t.sent:
        assert m["To"] == "+919876543210" and m["Body"].startswith("Swasthya Saathi: ")
        assert "confirm the time" not in m["Body"]  # a clinic-confirmed slot needs no extra call
    notes = c.get(f"{P}/notifications?limit=100", headers=auth).json()
    assert notes["total"] == 2  # the in-app reminders were delivered as well


def test_not_opted_in_means_no_text(make_client):
    c = make_client(**SMS_ENV)
    t = Twilio()
    wire(c, t)
    auth, _ = book_visit(c)
    deliver_all(c, auth)
    assert t.sent == []


def test_server_without_sms_still_delivers_in_app(make_client):
    c = make_client()
    auth, _ = book_visit(c)
    c.put(f"{P}/preferences", json={"sms_reminders": True}, headers=auth)
    assert deliver_all(c, auth) == 2


def test_a_failing_sms_provider_never_blocks_the_in_app_reminder(make_client):
    c = make_client(**SMS_ENV)
    t = Twilio(status=500, body={"code": 20500})
    wire(c, t)
    auth, _ = book_visit(c)
    c.put(f"{P}/preferences", json={"sms_reminders": True}, headers=auth)
    assert deliver_all(c, auth) == 2
    assert c.get(f"{P}/notifications?limit=100", headers=auth).json()["total"] == 2


def test_an_unreachable_sms_provider_never_blocks_the_in_app_reminder(make_client):
    c = make_client(**SMS_ENV)

    def boom(request):
        raise httpx.ConnectError("down")

    c.app.state.reminder_service.sms.http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    auth, _ = book_visit(c)
    c.put(f"{P}/preferences", json={"sms_reminders": True}, headers=auth)
    assert deliver_all(c, auth) == 2


def test_each_reminder_is_texted_once(make_client):
    c = make_client(**SMS_ENV)
    t = Twilio()
    wire(c, t)
    auth, _ = book_visit(c)
    c.put(f"{P}/preferences", json={"sms_reminders": True}, headers=auth)
    deliver_all(c, auth)
    assert deliver_all(c, auth) == 0  # nothing is due any more
    assert len(t.sent) == 2


def test_the_rating_prompt_after_the_visit_is_not_texted(make_client):
    c = make_client(**SMS_ENV)
    t = Twilio()
    wire(c, t)
    auth, _ = book_visit(c)
    c.put(f"{P}/preferences", json={"sms_reminders": True}, headers=auth)
    after = max(when(a) for a in appointments(c, auth)) + timedelta(days=2)
    assert c.portal.call(c.app.state.reminder_service.deliver_due, after) == 1  # only the feedback request is still due
    assert t.sent == []
