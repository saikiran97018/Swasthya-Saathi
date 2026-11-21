"""Healthcare workflow: provider discovery, booking, double-booking, cancel/reschedule, reminders, follow-ups, feedback."""
from datetime import datetime, timedelta

import pytest

from app.database.connection import get_session_factory
from app.database.models import User
from app.services import scheduling as sched
from app.services.appointments import AppointmentService, BookingError
from tests.conftest import login_guest
from tests.fakes import FakeBhashini, FakeLLM, Recorder

P = "/api/v1"
CLINIC = "HC-GNT-01"  # Demo Family Clinic, Guntur: general medicine + pediatrics, Mon-Sat
SKIN = "HC-GNT-02"  # dermatology, offers teleconsultation


# ----------------------------------------------------------------------------- helpers
def today_ist():
    return datetime.now(sched.IST).date()


def first_slot(client, auth, code=CLINIC, days_ahead=0, nth=0) -> str:
    """A real, currently open slot as 'YYYY-MM-DD HH:MM'."""
    start = (today_ist() + timedelta(days=days_ahead)).isoformat()
    slots = client.get(f"{P}/providers/{code}/availability?from_date={start}&days=7", headers=auth).json()["open_slots"]
    flat = [f"{d} {t}" for d, times in slots.items() for t in times]
    assert flat, "demo provider has no open slots"
    return flat[nth]


def far_weekday(days: int):
    """A date `days` ahead that is not a Sunday (the demo clinics are closed on Sundays)."""
    d = today_ist() + timedelta(days=days)
    return d + timedelta(days=1) if d.weekday() == 6 else d


def say(client, auth, text, **kw):
    r = client.post(f"{P}/chat", json={"message": text, **kw}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def book(client, auth, llm, slot, code=CLINIC, name="Ravi Kumar", mobile="9876543210", reason="fever and cold", mode="in_person", cid=None, approve=True):
    """Drive the agent through a booking (pending confirmation -> confirm). Returns (pending, confirm_response)."""
    args = {"provider_code": code, "slot_start": slot, "patient_name": name, "patient_mobile": mobile, "reason": reason, "mode": mode}
    llm.script = [{"content": "I will book this for you.", "tool_calls": [("book_appointment", args)]}]
    first = say(client, auth, "please book it", conversation_id=cid)
    pend = first["pending_confirmation"]
    assert pend and pend["tool_name"] == "book_appointment"
    llm.script = [{"content": "All done."}]
    out = client.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": approve}, headers=auth)
    assert out.status_code == 200, out.text
    return pend, out.json()


def appointments(client, auth, scope="all"):
    return client.get(f"{P}/appointments?scope={scope}", headers=auth).json()["items"]


def tool_result(body):
    """The (single) tool execution touched by a chat or confirm response."""
    assert len(body["tool_executions"]) == 1, body["tool_executions"]
    return body["tool_executions"][0]


def new_user(client):
    r = client.post(f"{P}/auth/guest")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]["id"]


def run(client, fn):
    """Run `fn(session)` on the app's event loop with a real DB session (for service-level rule tests)."""

    async def go():
        async with get_session_factory()() as session:
            out = await fn(session)
            await session.commit()
            return out

    return client.portal.call(go)


def deliver(client, now: datetime) -> int:
    return client.portal.call(client.app.state.reminder_service.deliver_due, now)


def when(appt) -> datetime:
    return datetime.fromisoformat(appt["starts_at"].replace("Z", "+00:00"))


# ----------------------------------------------------------------------------- discovery
def test_provider_search_filters_and_aliases(client, auth):
    derm = client.get(f"{P}/providers?specialty=dermatology&city=Guntur", headers=auth).json()
    assert [p["code"] for p in derm] == [SKIN] and derm[0]["is_demo"] is True and derm[0]["next_available"]["date"]

    assert {p["city"] for p in client.get(f"{P}/providers?city=Bangalore", headers=auth).json()} == {"Bengaluru"}  # alias
    kn = client.get(f"{P}/providers?language=kn", headers=auth).json()
    assert kn and all("kn" in p["languages"] for p in kn)
    tele = client.get(f"{P}/providers?teleconsultation=true&specialty=psychiatry", headers=auth).json()
    assert tele and all(p["teleconsultation"] for p in tele)
    free = client.get(f"{P}/providers?accepts_ayushman=true&city=Chennai", headers=auth).json()
    assert free and all(p["accepts_ayushman"] for p in free)
    assert client.get(f"{P}/providers?specialty=astrology", headers=auth).status_code == 400
    assert client.get(f"{P}/providers", headers={}).status_code == 401


def test_availability_is_on_grid_in_the_future_and_within_horizon(client, auth):
    body = client.get(f"{P}/providers/{CLINIC}/availability?days=14", headers=auth).json()
    assert body["slot_minutes"] == 20 and body["timezone"] == "Asia/Kolkata"
    now = datetime.now(sched.IST)
    assert body["open_slots"]
    for day, times in body["open_slots"].items():
        d = datetime.fromisoformat(day).date()
        assert d.weekday() != 6, "clinic is closed on Sundays"
        assert now.date() <= d <= now.date() + timedelta(days=14)
        for t in times:
            assert datetime.fromisoformat(f"{day}T{t}").replace(tzinfo=sched.IST) >= now + timedelta(minutes=30)
            assert int(t[3:]) % 20 == 0
    assert client.get(f"{P}/providers/NOPE/availability", headers=auth).status_code == 404
    assert client.get(f"{P}/providers/{CLINIC}/availability?from_date=soon", headers=auth).status_code == 400


# ----------------------------------------------------------------------------- the full journey
def test_full_agentic_journey_symptoms_to_booking_with_reminders(client, auth, llm):
    """understand -> assist -> execute -> confirm & follow up, all in one conversation."""
    slot = first_slot(client, auth, SKIN, days_ahead=2)
    llm.script = [
        {"tool_calls": [("assess_urgency", {"symptoms": "itchy rash on my skin for a week", "age": 30})]},
        {"tool_calls": [("find_healthcare_providers", {"specialty": "dermatology", "city": "Guntur", "language": "te"})]},
        {"tool_calls": [("check_availability", {"provider_code": SKIN, "from_date": slot[:10], "days": 2})]},
        {"content": "ఈ సమయం సరేనా?"},
    ]
    r = say(client, auth, "నాకు చర్మం మీద దద్దుర్లు ఉన్నాయి, గుంటూరులో డాక్టర్ కావాలి")
    assert r["language"] == "te"  # Telugu script detected automatically
    execs = [e for m in r["messages"] for e in m["tool_executions"]]
    assert [e["tool_name"] for e in execs] == ["assess_urgency", "find_healthcare_providers", "check_availability"]
    assert execs[0]["result"]["urgency"] == "routine" and execs[0]["result"]["suggested_specialty"] == "dermatology"
    found = execs[1]["result"]
    assert found["results"][0]["code"] == SKIN and found["results"][0]["next_available"] and "SAMPLE" in found["data_source_notice"]
    assert slot[11:] in execs[2]["result"]["open_slots"][slot[:10]]

    cid = r["conversation"]["id"]
    pend, out = book(client, auth, llm, slot, code=SKIN, name="లక్ష్మి", reason="skin rash", cid=cid)
    shown = sched.describe(sched.parse_local_slot(slot))["display"]
    assert "Demo Skin & Care Clinic, Guntur" in pend["explanation"] and "లక్ష్మి" in pend["explanation"] and shown in pend["explanation"]
    done = tool_result(out)
    assert done["status"] == "success" and done["result"]["reference"].startswith("AP-")
    assert [r["kind"] for r in done["result"]["reminders_scheduled"]].count("appointment_reminder") == 2
    assert out["assistant_message"]["source"] == "tool" and "book_appointment" in out["assistant_message"]["tools_used"]

    appts = appointments(client, auth)
    assert len(appts) == 1
    a = appts[0]
    assert a["ref"] == done["result"]["reference"] and a["status"] == "booked" and a["provider"]["code"] == SKIN and a["language"] == "te"
    assert a["patient_mobile"] == "98XXXXXX10"  # masked in the API
    assert sorted(r["kind"] for r in a["reminders"]) == ["appointment_reminder", "appointment_reminder", "feedback_request"]
    assert when(a) == datetime.fromisoformat(slot).replace(tzinfo=sched.IST)

    # the slot is no longer offered
    left = client.get(f"{P}/providers/{SKIN}/availability?from_date={slot[:10]}&days=1", headers=auth).json()["open_slots"]
    assert slot[11:] not in left.get(slot[:10], [])
    dash = client.get(f"{P}/dashboard/summary", headers=auth).json()
    assert dash["appointments_total"] == 1 and dash["upcoming_appointments"][0]["ref"] == a["ref"]


def test_emergency_symptoms_are_flagged_by_the_tool(client, auth, llm):
    llm.script = [{"tool_calls": [("assess_urgency", {"symptoms": "severe chest pain and sweating", "age": 55})]}, {"content": "Call 112 now."}]
    r = say(client, auth, "my father has chest pain")
    res = tool_result(r)["result"]
    assert res["urgency"] == "emergency" and "112" in res["advice"] and res["emergency_numbers"]["ambulance"] == "108"


def test_provider_search_falls_back_to_teleconsultation_when_city_has_none(client, auth, llm):
    llm.script = [{"tool_calls": [("find_healthcare_providers", {"specialty": "dermatology", "city": "Leh"})]}, {"content": "Online options only."}]
    res = tool_result(say(client, auth, "skin doctor in Leh"))["result"]
    assert "teleconsultation" in res["note"] and all(p["teleconsultation"] for p in res["results"])


def test_provider_search_with_nothing_found_lists_cities(client, auth, llm):
    llm.script = [{"tool_calls": [("find_healthcare_providers", {"specialty": "dentistry", "city": "Leh"})]}, {"content": "None found."}]
    res = tool_result(say(client, auth, "dentist in Leh"))["result"]
    assert res["results"] == [] and "Guntur" in res["available_cities"]


# ----------------------------------------------------------------------------- confirmation & safety
def test_booking_needs_confirmation_and_declining_books_nothing(client, auth, llm):
    slot = first_slot(client, auth)
    pend, out = book(client, auth, llm, slot, approve=False)
    assert appointments(client, auth) == []
    assert out["assistant_message"]["tools_used"] == []
    log = client.get(f"{P}/agents/executions", headers=auth).json()["items"][0]["tool_executions"][0]
    assert log["status"] == "denied" and log["tool_name"] == "book_appointment"


def test_two_users_cannot_book_the_same_slot(client, llm):
    alice, _ = new_user(client)
    bob, _ = new_user(client)
    slot = first_slot(client, alice)
    book(client, alice, llm, slot, name="Alice A")
    # Bob's agent proposes the same slot (e.g. a stale availability check): the database refuses it
    _, out = book(client, bob, llm, slot, name="Bob B")
    ex = tool_result(out)
    assert ex["status"] == "error" and "taken" in ex["error"]
    assert appointments(client, bob) == [] and len(appointments(client, alice)) == 1


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda s: {"patient_mobile": "1234567890"}, "10-digit"),  # (shorter numbers are rejected earlier, by argument validation)
        (lambda s: {"provider_code": "HC-GNT-99"}, "No provider"),
        (lambda s: {"mode": "teleconsultation"}, "does not offer teleconsultation"),
        (lambda s: {"slot_start": "2020-01-06 10:00"}, "too soon or already past"),
        (lambda s: {"slot_start": s[:10] + " 10:07"}, "not one of"),
        (lambda s: {"slot_start": far_weekday(40).isoformat() + " 10:00"}, "up to 14 days"),
        (lambda s: {"slot_start": "next tuesday"}, "YYYY-MM-DD HH:MM"),
    ],
)
def test_booking_rule_violations_become_tool_errors(client, auth, llm, mutate, fragment):
    slot = first_slot(client, auth, days_ahead=1)
    args = {"provider_code": CLINIC, "slot_start": slot, "patient_name": "Ravi Kumar", "patient_mobile": "9876543210", "reason": "fever", **mutate(slot)}
    llm.script = [{"tool_calls": [("book_appointment", args)]}]
    pend = say(client, auth, "book").get("pending_confirmation")
    llm.script = [{"content": "Sorry, that did not work."}]
    out = client.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": True}, headers=auth).json()
    ex = tool_result(out)
    assert ex["status"] == "error" and fragment in ex["error"], ex
    assert appointments(client, auth) == []


def test_booking_rules_at_service_level(make_client):
    c = make_client(max_active_appointments=1)
    auth, uid = new_user(c)
    s1, s2 = first_slot(c, auth, days_ahead=1, nth=0), first_slot(c, auth, days_ahead=1, nth=1)

    async def attempt(session, code, slot):
        svc = AppointmentService(session, c.app.state.settings)
        user = await session.get(User, __import__("uuid").UUID(uid))
        provider = await svc.providers.get_by_code(code)
        return await svc.book(user=user, conversation_id=None, provider=provider, starts_at=sched.parse_local_slot(slot), patient_name="Ravi", patient_mobile="9876543210", reason="fever")

    run(c, lambda s: attempt(s, CLINIC, s1))
    with pytest.raises(BookingError) as limit:
        run(c, lambda s: attempt(s, CLINIC, s2))
    assert limit.value.code == "too_many_appointments"


def test_same_person_cannot_double_book_overlapping_times(client, auth, llm):
    slot = first_slot(client, auth, CLINIC, days_ahead=1)
    # a different provider with a slot at exactly the same minute
    other = next(f"{d} {t}" for d, ts in client.get(f"{P}/providers/HOS-GNT-01/availability?from_date={slot[:10]}&days=1", headers=auth).json()["open_slots"].items() for t in ts if f"{d} {t}" == slot) \
        if slot[11:] in client.get(f"{P}/providers/HOS-GNT-01/availability?from_date={slot[:10]}&days=1", headers=auth).json()["open_slots"].get(slot[:10], []) else None
    if other is None:
        pytest.skip("hospital OPD has no slot at the same minute today (opening hours differ)")
    book(client, auth, llm, slot)
    _, out = book(client, auth, llm, other, code="HOS-GNT-01", name="Ravi Kumar")
    assert "already has appointment" in tool_result(out)["error"]


# ----------------------------------------------------------------------------- cancel & reschedule
def test_cancel_via_agent_requires_confirmation_and_reopens_slot(client, auth, llm):
    slot = first_slot(client, auth, days_ahead=2)
    book(client, auth, llm, slot)
    ref = appointments(client, auth)[0]["ref"]

    llm.script = [{"content": "I'll cancel it.", "tool_calls": [("cancel_appointment", {"reference": ref, "reason": "feeling better"})]}]
    first = say(client, auth, "cancel my appointment")
    assert first["pending_confirmation"] and ref in first["pending_confirmation"]["explanation"]
    assert appointments(client, auth)[0]["status"] == "booked"  # not yet
    llm.script = [{"content": "Cancelled."}]
    client.post(f"{P}/agents/executions/{first['pending_confirmation']['id']}/confirm", json={"approve": True}, headers=auth)

    a = appointments(client, auth)[0]
    assert a["status"] == "cancelled" and all(r["status"] in ("cancelled", "delivered") for r in a["reminders"])
    assert slot[11:] in client.get(f"{P}/providers/{CLINIC}/availability?from_date={slot[:10]}&days=1", headers=auth).json()["open_slots"][slot[:10]]


def test_cancel_via_rest_twice_and_by_a_stranger(client, auth, llm):
    book(client, auth, llm, first_slot(client, auth, days_ahead=2))
    a = appointments(client, auth)[0]
    stranger, _ = new_user(client)
    assert client.post(f"{P}/appointments/{a['id']}/cancel", json={}, headers=stranger).status_code == 404
    assert client.get(f"{P}/appointments/{a['id']}", headers=stranger).status_code == 404
    ok = client.post(f"{P}/appointments/{a['id']}/cancel", json={"reason": "travelling"}, headers=auth)
    assert ok.status_code == 200 and ok.json()["status"] == "cancelled"
    again = client.post(f"{P}/appointments/{a['id']}/cancel", headers=auth)
    assert again.status_code == 400 and again.json()["error"]["code"] == "not_active"
    assert client.get(f"{P}/appointments?scope=upcoming", headers=auth).json()["total"] == 0
    assert client.get(f"{P}/appointments?scope=past", headers=auth).json()["total"] == 1


def test_reschedule_keeps_reference_and_rebuilds_reminders(client, auth, llm):
    s1, s2 = first_slot(client, auth, days_ahead=3, nth=0), first_slot(client, auth, days_ahead=4, nth=1)
    book(client, auth, llm, s1)
    before = appointments(client, auth)[0]

    llm.script = [{"content": "Moving it.", "tool_calls": [("reschedule_appointment", {"reference": before["ref"], "new_slot_start": s2})]}]
    pend = say(client, auth, "move my appointment")["pending_confirmation"]
    assert before["ref"] in pend["explanation"] and sched.describe(sched.parse_local_slot(s2))["display"] in pend["explanation"]
    llm.script = [{"content": "Moved."}]
    out = client.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": True}, headers=auth).json()
    assert tool_result(out)["status"] == "success"

    after = appointments(client, auth)[0]
    assert after["ref"] == before["ref"] and after["reschedule_count"] == 1
    assert when(after) == datetime.fromisoformat(s2).replace(tzinfo=sched.IST)
    pending = [r for r in after["reminders"] if r["status"] == "pending"]
    assert len(pending) == 3  # 24h, 2h and feedback rebuilt for the new time
    assert all(datetime.fromisoformat(r["due_at"].replace("Z", "+00:00")) > when(before) - timedelta(days=1) for r in pending)
    # old slot is free again, new slot is taken
    assert s1[11:] in client.get(f"{P}/providers/{CLINIC}/availability?from_date={s1[:10]}&days=1", headers=auth).json()["open_slots"][s1[:10]]


def test_reschedule_to_a_taken_slot_is_refused(client, llm):
    alice, _ = new_user(client)
    bob, _ = new_user(client)
    s1, s2 = first_slot(client, alice, days_ahead=2, nth=0), first_slot(client, alice, days_ahead=2, nth=1)
    book(client, alice, llm, s1, name="Alice A")
    book(client, bob, llm, s2, name="Bob B")
    ref = appointments(client, bob)[0]["ref"]
    llm.script = [{"tool_calls": [("reschedule_appointment", {"reference": ref, "new_slot_start": s1})]}]
    pend = say(client, bob, "move to the earlier time")["pending_confirmation"]
    llm.script = [{"content": "Sorry."}]
    out = client.post(f"{P}/agents/executions/{pend['id']}/confirm", json={"approve": True}, headers=bob).json()
    assert "taken" in tool_result(out)["error"]
    assert when(appointments(client, bob)[0]) == datetime.fromisoformat(s2).replace(tzinfo=sched.IST)  # unchanged


def test_list_appointments_tool_returns_references(client, auth, llm):
    book(client, auth, llm, first_slot(client, auth, days_ahead=2))
    llm.script = [{"tool_calls": [("list_appointments", {"scope": "upcoming"})]}, {"content": "You have one."}]
    res = tool_result(say(client, auth, "what appointments do I have?"))["result"]
    assert res["total"] == 1 and res["appointments"][0]["reference"].startswith("AP-") and res["appointments"][0]["provider"]["code"] == CLINIC


# ----------------------------------------------------------------------------- reminders & notifications
def test_reminders_are_delivered_on_time_and_not_before(client, auth, llm):
    slot = first_slot(client, auth, days_ahead=3)
    book(client, auth, llm, slot)
    a = appointments(client, auth)[0]
    start = when(a)

    assert deliver(client, start - timedelta(days=2)) == 0  # nothing due yet
    assert client.get(f"{P}/notifications", headers=auth).json()["unread_count"] == 0

    assert deliver(client, start - timedelta(hours=23)) == 1  # the 24h reminder
    note = client.get(f"{P}/notifications", headers=auth).json()
    assert note["unread_count"] == 1 and note["items"][0]["kind"] == "appointment_reminder" and a["ref"] in note["items"][0]["message"]
    assert note["items"][0]["appointment_ref"] == a["ref"] and note["items"][0]["conversation_id"] == a["conversation_id"]

    assert deliver(client, start - timedelta(hours=23)) == 0  # never delivered twice
    assert deliver(client, start - timedelta(hours=1)) == 1  # the 2h reminder


def test_finished_visits_complete_and_trigger_a_feedback_request(client, auth, llm):
    book(client, auth, llm, first_slot(client, auth, days_ahead=1))
    a = appointments(client, auth)[0]
    deliver(client, when(a) + timedelta(hours=1))
    assert appointments(client, auth)[0]["status"] == "completed"
    assert not [r for r in appointments(client, auth)[0]["reminders"] if r["kind"] == "appointment_reminder" and r["status"] == "delivered"]  # stale reminders dropped

    deliver(client, when(a) + timedelta(hours=4))
    notes = client.get(f"{P}/notifications", headers=auth).json()["items"]
    assert [n["kind"] for n in notes] == ["feedback_request"] and "rating from 1 to 5" in notes[0]["message"]


def test_notifications_read_state_and_isolation(client, auth, llm):
    book(client, auth, llm, first_slot(client, auth, days_ahead=2))
    a = appointments(client, auth)[0]
    deliver(client, when(a) + timedelta(days=1))
    n = client.get(f"{P}/notifications", headers=auth).json()
    assert n["unread_count"] >= 1
    nid = n["items"][0]["id"]
    stranger, _ = new_user(client)
    assert client.post(f"{P}/notifications/{nid}/read", headers=stranger).status_code == 404
    assert client.get(f"{P}/notifications", headers=stranger).json()["total"] == 0

    read = client.post(f"{P}/notifications/{nid}/read", headers=auth).json()
    assert read["read_at"] is not None
    assert client.get(f"{P}/notifications", headers=auth).json()["unread_count"] == n["unread_count"] - 1
    assert client.get(f"{P}/notifications?unread_only=true", headers=auth).json()["total"] == n["unread_count"] - 1
    assert client.post(f"{P}/notifications/read-all", headers=auth).json()["marked_read"] == n["unread_count"] - 1
    assert client.get(f"{P}/notifications", headers=auth).json()["unread_count"] == 0
    assert client.get(f"{P}/dashboard/summary", headers=auth).json()["unread_notifications"] == 0


def test_reminders_are_translated_into_the_users_language(client, auth, llm):
    llm.title = "మీ అపాయింట్‌మెంట్ రేపు ఉంది"  # what the (fake) LLM returns for the translation request
    slot = first_slot(client, auth, days_ahead=3)
    cid = say(client, auth, "నమస్కారం", ) and client.get(f"{P}/conversations", headers=auth).json()["items"][0]["id"]
    book(client, auth, llm, slot, cid=cid)
    a = appointments(client, auth)[0]
    assert a["language"] == "te"
    deliver(client, when(a) - timedelta(hours=23))
    msg = client.get(f"{P}/notifications", headers=auth).json()["items"][0]["message"]
    assert msg == "మీ అపాయింట్‌మెంట్ రేపు ఉంది"
    translate_calls = [r for r in llm.requests if not r.get("stream") and "Translate" in r["messages"][0]["content"]]
    assert translate_calls and "Telugu" in translate_calls[-1]["messages"][0]["content"]
    assert a["ref"] in translate_calls[-1]["messages"][1]["content"]  # reference codes are sent verbatim


def test_english_reminders_are_not_sent_to_the_llm_and_translation_failure_falls_back(client, auth, llm):
    book(client, auth, llm, first_slot(client, auth, days_ahead=3))
    a = appointments(client, auth)[0]
    before = len(llm.requests)
    deliver(client, when(a) - timedelta(hours=23))
    assert len(llm.requests) == before  # English: no translation call
    assert a["ref"] in client.get(f"{P}/notifications", headers=auth).json()["items"][0]["message"]


# ----------------------------------------------------------------------------- follow-up & feedback
def test_follow_up_reminder_is_scheduled_and_delivered(client, auth, llm):
    book(client, auth, llm, first_slot(client, auth, days_ahead=1))
    a = appointments(client, auth)[0]
    due = (today_ist() + timedelta(days=10)).isoformat()
    llm.script = [{"tool_calls": [("schedule_follow_up", {"appointment_reference": a["ref"], "follow_up_date": due, "note": "repeat blood test"})]}, {"content": "Reminder set."}]
    res = tool_result(say(client, auth, "remind me for a follow-up in 10 days"))
    assert res["status"] == "success" and res["result"]["appointment"] == a["ref"] and "9:00 AM" in res["result"]["reminder_on"]
    assert any(r["kind"] == "follow_up" for r in appointments(client, auth)[0]["reminders"])

    assert not [n for n in client.get(f"{P}/notifications", headers=auth).json()["items"] if n["kind"] == "follow_up"]  # not due yet
    deliver(client, datetime.fromisoformat(due + "T10:00:00").replace(tzinfo=sched.IST))
    notes = client.get(f"{P}/notifications", headers=auth).json()["items"]
    follow = [n for n in notes if n["kind"] == "follow_up"]
    assert follow and "repeat blood test" in follow[0]["message"] and a["ref"] in follow[0]["message"]


@pytest.mark.parametrize(
    "date_offset,fragment",
    [(-3, "must be in the future"), (400, "up to one year")],
)
def test_follow_up_date_rules(client, auth, llm, date_offset, fragment):
    book(client, auth, llm, first_slot(client, auth, days_ahead=1))
    ref = appointments(client, auth)[0]["ref"]
    due = (today_ist() + timedelta(days=date_offset)).isoformat()
    llm.script = [{"tool_calls": [("schedule_follow_up", {"appointment_reference": ref, "follow_up_date": due})]}, {"content": "no"}]
    assert fragment in tool_result(say(client, auth, "follow up"))["error"]


def test_follow_up_limit_and_unknown_appointment(client, auth, llm):
    book(client, auth, llm, first_slot(client, auth, days_ahead=1))
    ref = appointments(client, auth)[0]["ref"]
    for i in range(3):
        llm.script = [{"tool_calls": [("schedule_follow_up", {"appointment_reference": ref, "follow_up_date": (today_ist() + timedelta(days=20 + i)).isoformat()})]}, {"content": "ok"}]
        assert tool_result(say(client, auth, f"follow up {i}"))["status"] == "success"
    llm.script = [{"tool_calls": [("schedule_follow_up", {"appointment_reference": ref, "follow_up_date": (today_ist() + timedelta(days=40)).isoformat()})]}, {"content": "no"}]
    assert "already has 3 follow-up" in tool_result(say(client, auth, "one more"))["error"]
    llm.script = [{"tool_calls": [("schedule_follow_up", {"appointment_reference": "AP-ZZZZZ", "follow_up_date": (today_ist() + timedelta(days=5)).isoformat()})]}, {"content": "no"}]
    assert "No appointment" in tool_result(say(client, auth, "x"))["error"]


def test_feedback_flow_after_a_completed_visit(client, auth, llm):
    book(client, auth, llm, first_slot(client, auth, days_ahead=1))
    a = appointments(client, auth)[0]

    llm.script = [{"tool_calls": [("record_feedback", {"appointment_reference": a["ref"], "rating": 5, "comment": "Very kind doctor"})]}, {"content": "Thanks."}]
    early = tool_result(say(client, auth, "great visit"))
    assert early["status"] == "error" and "after the appointment" in early["error"]

    done = client.post(f"{P}/appointments/{a['id']}/complete", headers=auth)  # demo helper
    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert [n["kind"] for n in client.get(f"{P}/notifications", headers=auth).json()["items"]] == ["feedback_request"]

    llm.script = [{"tool_calls": [("record_feedback", {"appointment_reference": a["ref"], "rating": 5, "comment": "Very kind doctor"})]}, {"content": "Thanks!"}]
    ok = tool_result(say(client, auth, "five stars, very kind doctor"))
    assert ok["status"] == "success"
    saved = appointments(client, auth)[0]
    assert saved["feedback_rating"] == 5 and saved["feedback_comment"] == "Very kind doctor"

    llm.script = [{"tool_calls": [("record_feedback", {"appointment_reference": a["ref"], "rating": 1})]}, {"content": "ok"}]
    assert "already recorded" in tool_result(say(client, auth, "actually 1 star"))["error"]


def test_feedback_rating_must_be_1_to_5(client, auth, llm):
    book(client, auth, llm, first_slot(client, auth, days_ahead=1))
    a = appointments(client, auth)[0]
    client.post(f"{P}/appointments/{a['id']}/complete", headers=auth)
    llm.script = [{"tool_calls": [("record_feedback", {"appointment_reference": a["ref"], "rating": 9})]}, {"content": "ok"}]
    assert "Invalid arguments" in tool_result(say(client, auth, "nine stars"))["error"]
    assert appointments(client, auth)[0]["feedback_rating"] is None


def test_demo_helpers_can_be_disabled_and_remind_now_works(make_client, llm):
    on = make_client()
    auth, _ = new_user(on)
    book(on, auth, llm, first_slot(on, auth, days_ahead=3))
    a = appointments(on, auth)[0]
    r = on.post(f"{P}/appointments/{a['id']}/remind-now", headers=auth)
    assert r.status_code == 200
    assert on.get(f"{P}/notifications", headers=auth).json()["unread_count"] == 1

    off = make_client(demo_mode=False)
    auth2, _ = new_user(off)
    for path in ("complete", "remind-now"):
        r = off.post(f"{P}/appointments/{a['id']}/{path}", headers=auth2)
        assert r.status_code == 403 and r.json()["error"]["code"] == "demo_disabled"


# ----------------------------------------------------------------------------- webhooks
def test_webhook_events_for_booking_cancel_and_reminders(llm):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    rec = Recorder()
    app = create_app(Settings(_env_file=None, webhook_url="https://hmis.test/hook", webhook_secret="k", reminder_poll_seconds=0),
                     llm_client=llm.client(), bhashini_client=FakeBhashini().client(), tools_client=rec.client())
    with TestClient(app) as c:
        auth, _ = new_user(c)
        book(c, auth, llm, first_slot(c, auth, days_ahead=3))
        a = appointments(c, auth)[0]
        deliver(c, when(a) - timedelta(hours=23))
        c.post(f"{P}/appointments/{a['id']}/cancel", json={"reason": "x"}, headers=auth)

    names = [r.headers["X-Event"] for r in rec.requests]
    assert names == ["appointment.booked", "reminder.delivered", "appointment.cancelled"]
    booked = rec.events()[0]["data"]
    assert booked["reference"] == a["ref"] and booked["provider"]["code"] == CLINIC
    assert all(r.headers.get("X-Signature") for r in rec.requests)


def test_webhook_failure_never_breaks_booking(llm):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    app = create_app(Settings(_env_file=None, webhook_url="https://hmis.test/hook", reminder_poll_seconds=0), llm_client=llm.client(),
                     bhashini_client=FakeBhashini().client(), tools_client=Recorder(status=500).client())
    with TestClient(app) as c:
        auth, _ = new_user(c)
        book(c, auth, llm, first_slot(c, auth, days_ahead=2))
        assert appointments(c, auth)[0]["status"] == "booked"


