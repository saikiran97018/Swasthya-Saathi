"""Booking and feedback straight from the UI (REST), using the same rules as the agent's tools."""
from datetime import datetime, timedelta

import pytest

from app.services import scheduling as sched
from tests.conftest import login_guest
from tests.test_healthcare import CLINIC, SKIN, appointments, first_slot, new_user, today_ist, when

P = "/api/v1"


def body(slot: str, **over) -> dict:
    return {"provider_code": CLINIC, "slot_start": slot, "patient_name": "Ravi Kumar", "patient_mobile": "9876543210", "reason": "fever and cold", **over}


def book(client, auth, slot, **over):
    return client.post(f"{P}/appointments", json=body(slot, **over), headers=auth)


def test_requires_login(client):
    assert client.post(f"{P}/appointments", json=body("2030-01-01 10:00")).status_code == 401


def test_booking_returns_the_full_appointment_with_reminders(client, auth):
    slot = first_slot(client, auth, days_ahead=3)
    r = book(client, auth, slot)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["ref"].startswith("AP-") and a["status"] == "booked" and a["mode"] == "in_person"
    assert a["provider"]["code"] == CLINIC and a["patient_mobile"] == "98XXXXXX10"  # masked in the response
    assert when(a) == datetime.fromisoformat(slot).replace(tzinfo=sched.IST)
    assert sorted(x["kind"] for x in a["reminders"]) == ["appointment_reminder", "appointment_reminder", "feedback_request"]
    assert [x["ref"] for x in appointments(client, auth)] == [a["ref"]]
    left = client.get(f"{P}/providers/{CLINIC}/availability?from_date={slot[:10]}&days=1", headers=auth).json()["open_slots"]
    assert slot[11:] not in left.get(slot[:10], [])  # the slot is gone from availability


def test_language_defaults_to_the_users_primary_language_and_can_be_set(client, auth):
    client.put(f"{P}/preferences", json={"primary_language": "te"}, headers=auth)
    s1, s2 = first_slot(client, auth, days_ahead=3, nth=0), first_slot(client, auth, days_ahead=3, nth=1)
    assert book(client, auth, s1).json()["language"] == "te"
    assert book(client, auth, s2, language="hi").json()["language"] == "hi"


def test_two_people_cannot_book_the_same_slot(client):
    alice, _ = new_user(client)
    bob, _ = new_user(client)
    slot = first_slot(client, alice, days_ahead=2)
    assert book(client, alice, slot).status_code == 201
    r = book(client, bob, slot, patient_name="Bob B")
    assert r.status_code == 400 and r.json()["error"]["code"] == "slot_taken"
    assert appointments(client, bob) == []


@pytest.mark.parametrize(
    "over,status,code",
    [
        ({"patient_mobile": "1234567890"}, 400, "invalid_mobile"),
        ({"patient_mobile": "98765"}, 422, "validation_error"),
        ({"provider_code": "HC-GNT-99"}, 404, "provider_not_found"),
        ({"mode": "teleconsultation"}, 400, "no_teleconsultation"),  # the family clinic is in-person only
        ({"slot_start": "next tuesday"}, 400, "invalid_slot"),
        ({"slot_start": "2020-01-06 10:00"}, 400, "slot_in_past"),
        ({"patient_name": "R"}, 422, "validation_error"),
        ({"reason": "x"}, 422, "validation_error"),
    ],
)
def test_validation_and_rule_violations(client, auth, over, status, code):
    slot = first_slot(client, auth, days_ahead=2)
    if "slot_start" not in over:
        over = {**over, "slot_start": slot}
    r = client.post(f"{P}/appointments", json={**body(slot), **over}, headers=auth)
    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] == code
    assert appointments(client, auth) == []


def test_off_grid_time_and_too_far_ahead_are_refused(client, auth):
    slot = first_slot(client, auth, days_ahead=2)
    assert book(client, auth, slot[:10] + " 10:07").json()["error"]["code"] == "invalid_slot"
    d = today_ist() + timedelta(days=40)
    d += timedelta(days=1) if d.weekday() == 6 else timedelta()  # clinics are closed on Sundays
    r = book(client, auth, d.isoformat() + " 10:00")
    assert r.status_code == 400 and r.json()["error"]["code"] == "slot_too_far"


def test_teleconsultation_works_where_offered(client, auth):
    slot = first_slot(client, auth, SKIN, days_ahead=2)
    r = book(client, auth, slot, provider_code=SKIN, mode="teleconsultation")
    assert r.status_code == 201 and r.json()["mode"] == "teleconsultation"


def test_per_user_appointment_limit_applies(make_client):
    c = make_client(max_active_appointments=2)
    auth, _ = new_user(c)
    s0, s1, s2 = (first_slot(c, auth, days_ahead=2, nth=n) for n in (0, 1, 2))
    assert book(c, auth, s0).status_code == 201
    assert book(c, auth, s1).status_code == 201
    r = book(c, auth, s2)
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_many_appointments"


# ------------------------------------------------------------------------------------------------ feedback
def _completed(client, auth) -> dict:
    a = book(client, auth, first_slot(client, auth, days_ahead=1)).json()
    assert client.post(f"{P}/appointments/{a['id']}/complete", headers=auth).status_code == 200  # demo helper
    return a


def test_feedback_before_the_visit_is_refused(client, auth):
    a = book(client, auth, first_slot(client, auth, days_ahead=2)).json()
    r = client.post(f"{P}/appointments/{a['id']}/feedback", json={"rating": 5}, headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_early"


def test_feedback_is_saved_once_and_shows_in_provider_ratings(client, auth):
    assert all(p["rating_avg"] is None and p["rating_count"] == 0 for p in client.get(f"{P}/providers?city=Guntur", headers=auth).json())
    a = _completed(client, auth)
    r = client.post(f"{P}/appointments/{a['id']}/feedback", json={"rating": 4, "comment": "Kind doctor"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["feedback_rating"] == 4 and r.json()["feedback_comment"] == "Kind doctor"

    again = client.post(f"{P}/appointments/{a['id']}/feedback", json={"rating": 1}, headers=auth)
    assert again.status_code == 400 and again.json()["error"]["code"] == "already_rated"

    rated = {p["code"]: p for p in client.get(f"{P}/providers?city=Guntur", headers=auth).json()}
    assert rated[CLINIC]["rating_avg"] == 4.0 and rated[CLINIC]["rating_count"] == 1
    assert rated[SKIN]["rating_avg"] is None and rated[SKIN]["rating_count"] == 0  # never invented
    detail = client.get(f"{P}/providers/{CLINIC}/availability", headers=auth).json()["provider"]
    assert detail["rating_avg"] == 4.0 and detail["rating_count"] == 1


def test_ratings_are_averaged_across_patients(client, auth):
    a = _completed(client, auth)
    client.post(f"{P}/appointments/{a['id']}/feedback", json={"rating": 5}, headers=auth)
    other, _ = new_user(client)
    b = book(client, other, first_slot(client, other, days_ahead=1, nth=2), patient_name="Asha K").json()
    client.post(f"{P}/appointments/{b['id']}/complete", headers=other)
    client.post(f"{P}/appointments/{b['id']}/feedback", json={"rating": 2}, headers=other)
    p = next(x for x in client.get(f"{P}/providers?city=Guntur", headers=auth).json() if x["code"] == CLINIC)
    assert p["rating_avg"] == 3.5 and p["rating_count"] == 2


@pytest.mark.parametrize("rating", [0, 6, -1])
def test_rating_must_be_1_to_5(client, auth, rating):
    a = _completed(client, auth)
    r = client.post(f"{P}/appointments/{a['id']}/feedback", json={"rating": rating}, headers=auth)
    assert r.status_code == 422


def test_feedback_for_someone_elses_or_cancelled_appointment(client, auth):
    a = _completed(client, auth)
    stranger, _ = new_user(client)
    assert client.post(f"{P}/appointments/{a['id']}/feedback", json={"rating": 5}, headers=stranger).status_code == 404

    c = book(client, auth, first_slot(client, auth, days_ahead=3, nth=4)).json()
    client.post(f"{P}/appointments/{c['id']}/cancel", json={}, headers=auth)
    r = client.post(f"{P}/appointments/{c['id']}/feedback", json={"rating": 5}, headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_active"
