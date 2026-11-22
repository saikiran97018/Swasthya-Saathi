"""Symptom check-in, child vaccination tracker, and the note for the doctor."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.database.models import Reminder
from app.services import checkin, vaccines as vx
from app.services.doctor_summary import basic_note, patient_lines
from tests.test_healthcare import new_user, run, say

P = "/api/v1"
IST = timezone(timedelta(hours=5, minutes=30))


def reminders(client, kind):
    async def go(session):
        rows = (await session.scalars(select(Reminder).where(Reminder.kind == kind).order_by(Reminder.created_at))).all()
        return [(r.status, r.due_at, r.message, r.payload, r.conversation_id) for r in rows]

    return run(client, go)


# ======================================================================== 1. symptom check-in
def test_checkin_time_is_a_day_later_but_never_at_night():
    noon = datetime(2026, 11, 22, 6, 30, tzinfo=timezone.utc)  # 12:00 IST
    assert checkin.checkin_time(noon).astimezone(IST).strftime("%d %H:%M") == "23 12:00"
    late = datetime(2026, 11, 22, 17, 30, tzinfo=timezone.utc)  # 23:00 IST -> tomorrow 23:00 would be night
    assert checkin.checkin_time(late).astimezone(IST).strftime("%d %H:%M") == "24 08:00"
    early = datetime(2026, 11, 22, 21, 0, tzinfo=timezone.utc)  # 02:30 IST next day -> due 02:30 two days on
    assert checkin.checkin_time(early).astimezone(IST).hour == 8


def feel(client, auth, llm, symptoms="fever for two days", **kw):
    llm.script = [{"tool_calls": [("assess_urgency", {"symptoms": symptoms, **kw})]}, {"content": "See a doctor."}]
    return say(client, auth, f"I have {symptoms}")


def test_after_telling_saathi_how_they_feel_a_checkin_is_scheduled(client, llm):
    auth, _ = new_user(client)
    feel(client, auth, llm)
    rows = reminders(client, "symptom_checkin")
    assert len(rows) == 1
    status, due, message, payload, conv = rows[0]
    assert status == "pending" and "fever for two days" in message and payload["symptoms"] == "fever for two days" and conv is not None
    assert timedelta(hours=23) < due - datetime.now(timezone.utc) < timedelta(hours=34)


def test_only_one_checkin_waits_at_a_time(client, llm):
    auth, _ = new_user(client)
    feel(client, auth, llm, "fever")
    feel(client, auth, llm, "cough and sore throat")
    rows = reminders(client, "symptom_checkin")
    assert [r[0] for r in rows] == ["cancelled", "pending"] and "cough" in rows[1][2]


def test_an_emergency_gets_no_checkin(client, llm):
    auth, _ = new_user(client)
    feel(client, auth, llm, "chest pain and trouble breathing")
    assert reminders(client, "symptom_checkin") == []


def test_the_checkin_can_be_switched_off_in_settings(client, llm):
    auth, _ = new_user(client)
    assert client.get(f"{P}/preferences", headers=auth).json()["symptom_checkins"] is True
    assert client.put(f"{P}/preferences", json={"symptom_checkins": False}, headers=auth).json()["symptom_checkins"] is False
    feel(client, auth, llm)
    assert reminders(client, "symptom_checkin") == []


def test_the_checkin_reaches_the_bell_and_opens_the_same_chat(client, llm):
    auth, _ = new_user(client)
    first = feel(client, auth, llm)
    due = reminders(client, "symptom_checkin")[0][1]
    assert client.portal.call(client.app.state.reminder_service.deliver_due, due + timedelta(minutes=1)) >= 1
    notes = client.get(f"{P}/notifications?limit=10", headers=auth).json()["items"]
    n = next(x for x in notes if x["kind"] == "symptom_checkin")
    assert n["conversation_id"] == first["conversation"]["id"] and "fever" in n["message"]


# ======================================================================== 2. vaccination tracker: the rules
BORN = date(2026, 1, 10)


def status_of(items, key):
    return next(i["status"] for i in items if i["key"] == key)


def test_the_schedule_follows_uip_and_statuses_move_with_time():
    items = vx.schedule(BORN, date(2026, 1, 10), {})
    assert [i["key"] for i in items] == ["birth", "6w", "10w", "14w", "9m", "16m", "5y", "10y", "16y"]
    assert next(i for i in items if i["key"] == "6w")["due_on"] == date(2026, 2, 21)  # 42 days
    assert next(i for i in items if i["key"] == "9m")["due_on"] == date(2026, 10, 10)
    assert status_of(items, "birth") == "due" and status_of(items, "6w") == "upcoming"
    later = vx.schedule(BORN, date(2026, 4, 1), {})
    assert status_of(later, "birth") == "overdue" and status_of(later, "6w") == "overdue" and status_of(later, "10w") == "due" and status_of(later, "14w") == "upcoming"
    assert status_of(vx.schedule(BORN, date(2026, 4, 1), {"birth": date(2026, 1, 10), "6w": date(2026, 2, 21)}), "6w") == "given"


def test_the_vaccines_at_each_visit():
    by = {m.key: m.vaccines for m in vx.MILESTONES}
    assert "BCG" in by["birth"] and "Pentavalent 1" in by["6w"] and "Measles-Rubella 1" in by["9m"] and by["5y"] == ("DPT booster 2",)


def test_month_arithmetic_handles_month_ends_and_leap_days():
    assert vx.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert vx.add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert vx.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_only_children_are_covered():
    today = date(2026, 11, 22)
    assert vx.eligible(date(2020, 5, 5), today) and not vx.eligible(date(1980, 5, 5), today) and not vx.eligible(None, today) and not vx.eligible(date(2027, 1, 1), today)
    assert vx.eligible(date(2010, 12, 1), today) and not vx.eligible(date(2009, 11, 1), today)  # a 17th birthday ends it


def test_focus_picks_the_oldest_open_visit_else_the_next():
    today = date(2026, 4, 1)
    assert vx.focus(vx.schedule(BORN, today, {}), today)["key"] == "birth"  # the oldest overdue visit comes first
    assert vx.focus(vx.schedule(BORN, today, {"birth": date(2026, 1, 10)}), today)["key"] == "6w"
    done = vx.schedule(BORN, today, {"birth": date(2026, 1, 10), "6w": date(2026, 2, 21), "10w": date(2026, 3, 21)})
    assert vx.focus(done, today)["key"] == "14w"  # nothing overdue or due: the next upcoming one


# ======================================================================== 2. vaccination tracker: the API
def child(client, auth, born="2026-01-10", name="Aarav"):
    r = client.post(f"{P}/family", json={"name": name, "relation": "child", "birth_date": born}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def recent_birth(days=20):
    return (datetime.now(IST).date() - timedelta(days=days)).isoformat()


def test_a_child_with_a_birth_date_gets_a_schedule_and_reminders(client):
    auth, _ = new_user(client)
    m = child(client, auth, recent_birth())
    assert m["birth_date"] and m["birth_year"] == int(m["birth_date"][:4])
    v = client.get(f"{P}/family/{m['id']}/vaccinations", headers=auth).json()
    assert v["eligible"] is True and len(v["items"]) == 9 and "Universal Immunisation Programme" in v["schedule_name"] and "immunisation card" in v["disclaimer"]
    pend = [r for r in reminders(client, "vaccine") if r[0] == "pending"]
    assert 1 <= len(pend) <= 3 and all(r[3]["member_id"] == m["id"] for r in pend) and "Aarav" in pend[0][2]


def test_marking_a_visit_done_updates_the_schedule_and_the_reminders(client):
    auth, _ = new_user(client)
    m = child(client, auth, recent_birth(60))
    today = datetime.now(IST).date().isoformat()
    r = client.put(f"{P}/family/{m['id']}/vaccinations/birth", json={"given_on": recent_birth(59)}, headers=auth)
    assert r.status_code == 200 and next(i for i in r.json()["items"] if i["key"] == "birth")["status"] == "given"
    keys_before = {r[3]["milestone"] for r in reminders(client, "vaccine") if r[0] == "pending"}
    assert "birth" not in keys_before
    client.put(f"{P}/family/{m['id']}/vaccinations/6w", json={"given_on": today}, headers=auth)
    assert "6w" not in {r[3]["milestone"] for r in reminders(client, "vaccine") if r[0] == "pending"}
    undo = client.put(f"{P}/family/{m['id']}/vaccinations/6w", json={"given_on": None}, headers=auth).json()
    assert next(i for i in undo["items"] if i["key"] == "6w")["given_on"] is None


def test_bad_marks_are_refused(client):
    auth, _ = new_user(client)
    m = child(client, auth, recent_birth(60))
    url = f"{P}/family/{m['id']}/vaccinations"
    assert client.put(f"{url}/nope", json={"given_on": None}, headers=auth).status_code == 404
    future = (datetime.now(IST).date() + timedelta(days=3)).isoformat()
    assert client.put(f"{url}/6w", json={"given_on": future}, headers=auth).json()["error"]["code"] == "invalid_date"
    assert client.put(f"{url}/6w", json={"given_on": "2000-01-01"}, headers=auth).json()["error"]["code"] == "invalid_date"  # before the birth


def test_no_birth_date_or_too_old_means_no_schedule(client):
    auth, _ = new_user(client)
    nodate = client.post(f"{P}/family", json={"name": "Meena", "relation": "parent"}, headers=auth).json()
    assert client.get(f"{P}/family/{nodate['id']}/vaccinations", headers=auth).json()["reason"] == "no_birth_date"
    assert client.put(f"{P}/family/{nodate['id']}/vaccinations/birth", json={"given_on": None}, headers=auth).json()["error"]["code"] == "no_birth_date"
    old = child(client, auth, "1980-05-05", "Grandpa")
    v = client.get(f"{P}/family/{old['id']}/vaccinations", headers=auth).json()
    assert v["eligible"] is False and v["reason"] == "too_old" and v["items"] == []


def test_invalid_birth_dates_are_refused(client):
    auth, _ = new_user(client)
    future = (datetime.now(IST).date() + timedelta(days=5)).isoformat()
    assert client.post(f"{P}/family", json={"name": "Baby", "relation": "child", "birth_date": future}, headers=auth).json()["error"]["code"] == "invalid_birth_date"
    assert client.post(f"{P}/family", json={"name": "Old", "relation": "other", "birth_date": "1800-01-01"}, headers=auth).status_code in (400, 422)


def test_setting_or_changing_the_birth_date_rebuilds_the_reminders_and_deleting_removes_them(client):
    auth, _ = new_user(client)
    nodate = client.post(f"{P}/family", json={"name": "Anaya", "relation": "child"}, headers=auth).json()
    assert reminders(client, "vaccine") == []
    client.patch(f"{P}/family/{nodate['id']}", json={"birth_date": recent_birth(10)}, headers=auth)
    assert [r for r in reminders(client, "vaccine") if r[0] == "pending"]
    client.patch(f"{P}/family/{nodate['id']}", json={"birth_date": None}, headers=auth)
    assert not [r for r in reminders(client, "vaccine") if r[0] == "pending"]
    client.patch(f"{P}/family/{nodate['id']}", json={"birth_date": recent_birth(10)}, headers=auth)
    client.delete(f"{P}/family/{nodate['id']}", headers=auth)
    assert not [r for r in reminders(client, "vaccine") if r[0] == "pending"]


def test_vaccine_data_is_private(client):
    a, _ = new_user(client)
    b, _ = new_user(client)
    m = child(client, a, recent_birth())
    assert client.get(f"{P}/family/{m['id']}/vaccinations", headers=b).status_code == 404
    assert client.put(f"{P}/family/{m['id']}/vaccinations/birth", json={"given_on": None}, headers=b).status_code == 404
    assert client.get(f"{P}/family/{m['id']}/vaccinations").status_code == 401


def test_a_vaccine_reminder_reaches_the_bell(client):
    auth, _ = new_user(client)
    child(client, auth, recent_birth(5))
    due = max(r[1] for r in reminders(client, "vaccine"))
    client.portal.call(client.app.state.reminder_service.deliver_due, due + timedelta(minutes=1))
    kinds = {n["kind"] for n in client.get(f"{P}/notifications?limit=10", headers=auth).json()["items"]}
    assert "vaccine" in kinds


def test_the_assistant_knows_which_child_has_vaccines_due(client, llm):
    auth, _ = new_user(client)
    m = child(client, auth, recent_birth(50))  # about 7 weeks old: the 6-week visit is due now
    client.put(f"{P}/family/{m['id']}/vaccinations/birth", json={"given_on": recent_birth(49)}, headers=auth)  # the birth doses were given
    llm.script = [{"content": "Aarav's vaccines are due."}]
    say(client, auth, "when is my son's next vaccine")
    prompt = [r for r in llm.requests if r.get("stream")][-1]["messages"][0]["content"]
    assert "Child vaccines (UIP guide): Aarav: 6 weeks" in prompt and "due now" in prompt


# ======================================================================== 3. the note for the doctor
def talk(client, auth, llm):
    llm.script = [{"tool_calls": [("assess_urgency", {"symptoms": "fever for two days", "age": 34})]}, {"content": "See a doctor."}]
    out = say(client, auth, "I have had fever for two days and a bad headache. I take no other medicine.")
    return out["conversation"]["id"]


def test_the_note_is_written_from_the_patients_own_words(client, llm):
    auth, _ = new_user(client)
    cid = talk(client, auth, llm)
    llm.title = "Who: the patient, age 34\nMain problem: fever for two days and a bad headache\nHow long: two days\nOther symptoms: headache\nMedicines or allergies mentioned: no other medicine\nQuestions to ask the doctor: not mentioned"
    r = client.post(f"{P}/conversations/{cid}/doctor-note", headers=auth)
    assert r.status_code == 200 and r.json()["source"] == "assistant" and "fever for two days" in r.json()["text"]


def test_a_note_that_invents_things_is_replaced_by_a_plain_one(client, llm):
    auth, _ = new_user(client)
    cid = talk(client, auth, llm)
    llm.title = "Main problem: you have dengue. Take paracetamol 500 mg twice a day. Call 91234 56789 for the results."
    r = client.post(f"{P}/conversations/{cid}/doctor-note", headers=auth).json()
    assert r["source"] == "basic" and "dengue" not in r["text"] and "paracetamol" not in r["text"] and "fever for two days" in r["text"]
    assert "not a doctor" in r["text"]


def test_if_the_model_is_down_the_plain_note_still_works(make_client, llm):
    c = make_client()
    auth, _ = new_user(c)
    cid = talk(c, auth, llm)
    llm.fail_non_streaming = 500
    r = c.post(f"{P}/conversations/{cid}/doctor-note", headers=auth).json()
    assert r["source"] == "basic" and "fever for two days" in r["text"] and "age 34" in r["text"]


def test_the_note_is_private(client, llm):
    a, _ = new_user(client)
    b, _ = new_user(client)
    cid = talk(client, a, llm)
    assert client.post(f"{P}/conversations/{cid}/doctor-note", headers=b).status_code == 404
    assert client.post(f"{P}/conversations/{cid}/doctor-note").status_code == 401


def test_basic_note_limits_and_empty_chat():
    long = ["word " * 200] * 30
    lines = patient_lines(long)
    assert len(lines) == 12 and all(len(x) <= 400 for x in lines)
    assert "(nothing yet)" in basic_note([], None)
