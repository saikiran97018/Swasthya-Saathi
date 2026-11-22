"""Medical shops nearby, daily medicine reminders, and thumbs up/down on replies."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.database.models import Reminder
from app.main import create_app
from app.services import medicine as med
from app.services.intent import classify_rules
from tests.conftest import login_guest
from tests.fakes import FakeBhashini, FakeLLM, FakeOSM, fake_tools_client
from tests.test_healthcare import new_user, run, say

P = "/api/v1"
IST = timezone(timedelta(hours=5, minutes=30))

SHOPS = [
    {"type": "node", "id": 7001, "lat": 16.3080, "lon": 80.4380, "tags": {"name": "Apollo Pharmacy", "amenity": "pharmacy", "phone": "08632000111", "opening_hours": "Mo-Su 08:00-22:00", "addr:street": "Arundelpet", "addr:city": "Guntur"}},
    {"type": "node", "id": 7002, "lat": 16.3300, "lon": 80.4600, "tags": {"name": "Pradhan Mantri Jan Aushadhi Kendra", "amenity": "pharmacy"}},
    {"type": "node", "id": 7003, "lat": 16.2900, "lon": 80.4200, "tags": {"name": "Sri Sai Medicals", "amenity": "pharmacy"}},
    {"type": "node", "id": 7004, "lat": 16.3100, "lon": 80.4400, "tags": {"name": "Guntur General Hospital", "amenity": "hospital"}},
    {"type": "node", "id": 7005, "lat": 16.3500, "lon": 80.4800, "tags": {"amenity": "pharmacy"}},  # no name: skipped
]


def shop_app(**settings):
    llm = FakeLLM([{"content": "ok"}])
    app = create_app(
        Settings(_env_file=None, bhashini_user_id="u", bhashini_ulca_api_key="k", reminder_poll_seconds=0, overpass_url="", places_request_gap_seconds=0, **settings),
        llm_client=llm.client(), bhashini_client=FakeBhashini().client(), tools_client=fake_tools_client(), places_client=FakeOSM(elements=SHOPS).client(),
    )
    c = TestClient(app)
    c.__enter__()
    c.llm = llm
    return c


@pytest.fixture
def shops():
    c = shop_app()
    yield c
    c.__exit__(None, None, None)


# ======================================================================== medical shops nearby
def test_shop_search_lists_only_pharmacies_nearest_first(shops):
    h = login_guest(shops)
    body = shops.get(f"{P}/places/search", params={"city": "Guntur", "kind": "pharmacy"}, headers=h).json()
    assert [p["name"] for p in body["items"]] == ["Apollo Pharmacy", "Sri Sai Medicals", "Pradhan Mantri Jan Aushadhi Kendra"]  # no hospital, no unnamed pin
    assert all(p["kind"] == "pharmacy" and p["source"] == "openstreetmap" for p in body["items"])
    assert "Phone ahead" in body["note"] and "no online booking" not in body["note"]
    d = [p["distance_km"] for p in body["items"]]
    assert d == sorted(d)


def test_jan_aushadhi_shops_are_marked_and_chemists_have_no_medical_specialty(shops):
    h = login_guest(shops)
    items = {p["name"]: p for p in shops.get(f"{P}/places/search", params={"city": "Guntur", "kind": "pharmacy"}, headers=h).json()["items"]}
    assert items["Pradhan Mantri Jan Aushadhi Kendra"]["specialties"] == ["jan aushadhi"] and items["Apollo Pharmacy"]["specialties"] == []


def test_the_assistant_can_find_medical_shops(shops):
    auth, _ = new_user(shops)
    shops.llm.script = [{"tool_calls": [("find_medical_shops", {"city": "Guntur"})]}, {"content": "Apollo Pharmacy is nearest."}]
    out = say(shops, auth, "medical shop near me in Guntur")
    ex = out["tool_executions"][0]
    assert ex["tool_name"] == "find_medical_shops" and ex["status"] == "success"
    by_name = {s["name"]: s for s in ex["result"]["shops"]}
    assert list(by_name)[0] == "Apollo Pharmacy" and by_name["Pradhan Mantri Jan Aushadhi Kendra"]["jan_aushadhi"] is True and by_name["Apollo Pharmacy"]["jan_aushadhi"] is False
    assert by_name["Apollo Pharmacy"]["map"].startswith("https://www.openstreetmap.org/")


def test_the_tool_can_filter_to_jan_aushadhi(shops):
    auth, _ = new_user(shops)
    shops.llm.script = [{"tool_calls": [("find_medical_shops", {"city": "Guntur", "jan_aushadhi_only": True})]}, {"content": "One Kendra."}]
    ex = say(shops, auth, "cheap medicine shop in Guntur")["tool_executions"][0]
    assert [s["name"] for s in ex["result"]["shops"]] == ["Pradhan Mantri Jan Aushadhi Kendra"]


@pytest.mark.parametrize("text,label", [
    ("medical shop near me", "find_pharmacy"), ("is there a pharmacy nearby", "find_pharmacy"), ("मेडिकल स्टोर कहाँ है", "find_pharmacy"), ("दवा की दुकान", "find_pharmacy"),
    ("fever medicine shop", "find_pharmacy"),
    ("remind me to take my BP tablet at 8", "medicine_reminder"), ("set a medicine reminder", "medicine_reminder"), ("मुझे दवा लेने की याद दिलाओ", "medicine_reminder"),
])
def test_intent_recognises_the_new_requests(text, label):
    assert classify_rules(text) == label


# ======================================================================== medicine reminders: the rules
def test_times_are_cleaned_sorted_and_limited():
    assert med.clean_times(["8:00", "20:30", "08:00"]) == ["08:00", "20:30"]
    for bad in (["25:00"], ["8am"], [], ["08:00", "10:00", "12:00", "14:00", "16:00"]):
        with pytest.raises(med.MedicineError):
            med.clean_times(bad)


def test_labels_are_cleaned():
    assert med.clean_label("  BP\n tablet ") == "BP tablet"
    with pytest.raises(med.MedicineError):
        med.clean_label(" ")


def test_next_occurrence_is_today_if_ahead_else_tomorrow():
    now = datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc)  # 06:30 IST
    assert med.next_occurrence("08:00", now).astimezone(IST).strftime("%d %H:%M") == "22 08:00"
    assert med.next_occurrence("06:00", now).astimezone(IST).strftime("%d %H:%M") == "23 06:00"
    assert med.next_occurrence("06:30", now).astimezone(IST).strftime("%d %H:%M") == "23 06:30"  # "now" counts as passed


def reminder(due, ends="2026-12-31", repeat="daily", kind="medicine"):
    import uuid
    return Reminder(user_id=uuid.uuid4(), kind=kind, due_at=due, title="Medicine reminder", message="Time to take your BP tablet.", language="en",
                    payload={"series": "s1", "label": "BP tablet", "time": "08:00", "repeat": repeat, "ends_on": ends})


def test_the_next_dose_is_tomorrow_at_the_same_time():
    due = datetime(2026, 11, 22, 2, 30, tzinfo=timezone.utc)
    nxt = med.following_dose(reminder(due), due + timedelta(minutes=1))
    assert nxt.due_at == due + timedelta(days=1) and nxt.payload["series"] == "s1" and nxt.status in (None, "pending")


def test_missed_days_are_skipped_not_replayed():
    due = datetime(2026, 11, 22, 2, 30, tzinfo=timezone.utc)
    nxt = med.following_dose(reminder(due), due + timedelta(days=3, hours=1))  # the server was off for three days
    assert nxt.due_at == due + timedelta(days=4)


def test_a_series_ends_on_its_last_day_and_other_reminders_do_not_repeat():
    due = datetime(2026, 11, 22, 2, 30, tzinfo=timezone.utc)
    assert med.following_dose(reminder(due, ends="2026-11-22"), due) is None
    assert med.following_dose(reminder(due, repeat="once"), due) is None
    assert med.following_dose(reminder(due, kind="follow_up"), due) is None


# ======================================================================== medicine reminders: the API
def add(client, auth, **over):
    return client.post(f"{P}/medicine-reminders", json={"label": "BP tablet", "times": ["08:00", "20:00"], "days": 7, **over}, headers=auth)


def test_add_list_and_stop(client):
    auth, _ = new_user(client)
    r = add(client, auth)
    assert r.status_code == 201 and r.json()["label"] == "BP tablet" and r.json()["times"] == ["08:00", "20:00"]
    listed = client.get(f"{P}/medicine-reminders", headers=auth).json()
    assert len(listed) == 1 and listed[0]["series"] == r.json()["series"] and listed[0]["next_due"]
    assert client.delete(f"{P}/medicine-reminders/{r.json()['series']}", headers=auth).status_code == 204
    assert client.get(f"{P}/medicine-reminders", headers=auth).json() == []


@pytest.mark.parametrize("over", [{"times": ["25:00"]}, {"times": []}, {"label": " "}, {"days": 0}, {"days": 400}, {"times": ["01:00", "02:00", "03:00", "04:00", "05:00"]}])
def test_bad_input_is_refused(client, over):
    auth, _ = new_user(client)
    assert add(client, auth, **over).status_code in (400, 422)


def test_a_person_has_a_limited_number_of_reminders(client):
    auth, _ = new_user(client)
    for n in range(med.MAX_SERIES):
        assert add(client, auth, label=f"Tablet {n}").status_code == 201
    over = add(client, auth, label="One more")
    assert over.status_code == 409 and over.json()["error"]["code"] == "too_many_medicine_reminders"


def test_reminders_are_private(client):
    a, _ = new_user(client)
    b, _ = new_user(client)
    series = add(client, a).json()["series"]
    assert client.get(f"{P}/medicine-reminders", headers=b).json() == []
    assert client.delete(f"{P}/medicine-reminders/{series}", headers=b).status_code == 404
    assert len(client.get(f"{P}/medicine-reminders", headers=a).json()) == 1
    assert client.get(f"{P}/medicine-reminders").status_code == 401


def deliver(client, when):
    return client.portal.call(client.app.state.reminder_service.deliver_due, when)


def pending(client):
    async def go(session):
        from sqlalchemy import select
        return (await session.scalars(select(Reminder).where(Reminder.kind == "medicine").order_by(Reminder.due_at))).all()

    return [(r.status, r.due_at, r.delivered_message) for r in run(client, go)]


def test_a_dose_is_delivered_and_tomorrows_is_created(client):
    auth, _ = new_user(client)
    add(client, auth, times=["08:00"], days=5)
    due = pending(client)[0][1]
    assert deliver(client, due + timedelta(minutes=2)) == 1
    rows = pending(client)
    assert [s for s, _, _ in rows] == ["delivered", "pending"] and rows[1][1] == due + timedelta(days=1)
    notes = client.get(f"{P}/notifications?limit=10", headers=auth).json()
    assert notes["total"] == 1 and "BP tablet" in notes["items"][0]["message"]
    assert len(client.get(f"{P}/medicine-reminders", headers=auth).json()) == 1  # still one running reminder


def test_a_dose_that_is_hours_late_is_skipped_but_the_series_carries_on(client):
    auth, _ = new_user(client)
    add(client, auth, times=["08:00"], days=5)
    due = pending(client)[0][1]
    assert deliver(client, due + timedelta(hours=5)) == 0  # not announced: "take it now" five hours late would mislead
    rows = pending(client)
    assert rows[0][0] == "cancelled" and rows[1][0] == "pending" and rows[1][1] > due + timedelta(hours=5)
    assert client.get(f"{P}/notifications?limit=10", headers=auth).json()["total"] == 0


def test_the_series_ends_after_the_last_day(client):
    auth, _ = new_user(client)
    add(client, auth, times=["08:00"], days=1)
    due = pending(client)[0][1]
    deliver(client, due + timedelta(minutes=1))
    assert [s for s, _, _ in pending(client)] == ["delivered"]  # nothing created for tomorrow
    assert client.get(f"{P}/medicine-reminders", headers=auth).json() == []


def test_a_stopped_series_stops_for_good(client):
    auth, _ = new_user(client)
    series = add(client, auth, times=["08:00"], days=5).json()["series"]
    due = pending(client)[0][1]
    client.delete(f"{P}/medicine-reminders/{series}", headers=auth)
    assert deliver(client, due + timedelta(days=2)) == 0 and all(s == "cancelled" for s, _, _ in pending(client))


# ======================================================================== medicine reminders: through the assistant
def test_the_assistant_sets_lists_and_stops_reminders(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"tool_calls": [("medicine_reminder", {"action": "set", "label": "thyroid tablet", "times": ["07:00"], "days": 30})]}, {"content": "Done."}]
    ex = say(client, auth, "remind me to take my thyroid tablet at 7 every morning")["tool_executions"][0]
    assert ex["status"] == "success" and ex["result"]["times"] == ["07:00"]
    assert client.get(f"{P}/medicine-reminders", headers=auth).json()[0]["label"] == "thyroid tablet"
    llm.script = [{"tool_calls": [("medicine_reminder", {"action": "list"})]}, {"content": "One."}]
    assert say(client, auth, "what reminders do I have")["tool_executions"][0]["result"]["reminders"][0]["label"] == "thyroid tablet"
    llm.script = [{"tool_calls": [("medicine_reminder", {"action": "stop", "label": "thyroid"})]}, {"content": "Stopped."}]
    assert say(client, auth, "stop the thyroid reminder")["tool_executions"][0]["status"] == "success"
    assert client.get(f"{P}/medicine-reminders", headers=auth).json() == []


def test_the_assistant_gets_a_clear_error_for_a_bad_time(client, llm):
    auth, _ = new_user(client)
    llm.script = [{"tool_calls": [("medicine_reminder", {"action": "set", "label": "tablet", "times": ["25:99"]})]}, {"content": "Which time?"}]
    ex = say(client, auth, "remind me to take my tablet")["tool_executions"][0]
    assert ex["status"] == "error" and "not a time" in ex["error"]


# ======================================================================== thumbs up / down on replies
def reply_id(client, auth, llm):
    llm.script = [{"content": "Drink water."}]
    return say(client, auth, "I have a headache")["assistant_message"]["id"]


def rate(client, auth, mid, **body):
    return client.put(f"{P}/messages/{mid}/feedback", json=body, headers=auth)


def stored(client):
    async def go(session):
        from sqlalchemy import select
        from app.database.models import MessageFeedback
        return [(f.rating, f.reason, f.note) for f in (await session.scalars(select(MessageFeedback))).all()]

    return run(client, go)


def test_a_thumbs_down_keeps_the_reason_and_note(client, llm):
    auth, _ = new_user(client)
    mid = reply_id(client, auth, llm)
    r = rate(client, auth, mid, rating="down", reason="wrong_info", note="  It   said the wrong number\n")
    assert r.status_code == 200 and r.json() == {"message_id": mid, "rating": "down", "reason": "wrong_info"}
    assert stored(client) == [("down", "wrong_info", "It said the wrong number")]


def test_changing_the_vote_updates_it_and_an_up_vote_keeps_no_reason(client, llm):
    auth, _ = new_user(client)
    mid = reply_id(client, auth, llm)
    rate(client, auth, mid, rating="down", reason="unsafe", note="bad")
    rate(client, auth, mid, rating="up", reason="unsafe", note="bad")
    assert stored(client) == [("up", None, None)]  # one vote per person per reply


def test_the_vote_can_be_withdrawn(client, llm):
    auth, _ = new_user(client)
    mid = reply_id(client, auth, llm)
    rate(client, auth, mid, rating="down")
    assert client.delete(f"{P}/messages/{mid}/feedback", headers=auth).status_code == 204
    assert stored(client) == [] and client.delete(f"{P}/messages/{mid}/feedback", headers=auth).status_code == 204


def test_only_your_own_assistant_replies_can_be_rated(client, llm):
    a, _ = new_user(client)
    b, _ = new_user(client)
    mid = reply_id(client, a, llm)
    assert rate(client, b, mid, rating="down").status_code == 404  # someone else's conversation
    assert rate(client, a, "not-an-id", rating="down").status_code == 404
    assert rate(client, a, "00000000-0000-0000-0000-000000000000", rating="down").status_code == 404
    conv = client.get(f"{P}/conversations", headers=a).json()["items"][0]["id"]
    user_msg = next(m for m in client.get(f"{P}/conversations/{conv}", headers=a).json()["messages"] if m["role"] == "user")
    assert rate(client, a, user_msg["id"], rating="down").status_code == 404  # your own words are not a reply
    assert stored(client) == []


@pytest.mark.parametrize("body", [{"rating": "meh"}, {"rating": "down", "reason": "dislike"}, {"rating": "down", "note": "x" * 501}])
def test_bad_votes_are_refused(client, llm, body):
    auth, _ = new_user(client)
    assert rate(client, auth, reply_id(client, auth, llm), **body).status_code == 422


def test_rating_needs_login(client):
    assert client.put(f"{P}/messages/00000000-0000-0000-0000-000000000000/feedback", json={"rating": "up"}).status_code == 401


# ======================================================================== small towns: widen the circle, and "medical stores" tagged as shops
FAR = [  # Guntur is at 16.3067, 80.4365: these are ~11 km and ~14 km away, none nearby
    {"type": "node", "id": 8001, "lat": 16.4050, "lon": 80.4365, "tags": {"name": "Far Pharmacy", "amenity": "pharmacy"}},
    {"type": "node", "id": 8002, "lat": 16.4300, "lon": 80.4365, "tags": {"name": "Faraway Medical Stores", "shop": "chemist"}},
    {"type": "node", "id": 8003, "lat": 16.4400, "lon": 80.4365, "tags": {"name": "Farthest Medicals", "amenity": "pharmacy"}},
]


def town_app(elements):
    c = shop_app()
    c.__exit__(None, None, None)
    llm = FakeLLM([{"content": "ok"}])
    app = create_app(
        Settings(_env_file=None, bhashini_user_id="u", bhashini_ulca_api_key="k", reminder_poll_seconds=0, overpass_url="", places_request_gap_seconds=0),
        llm_client=llm.client(), bhashini_client=FakeBhashini().client(), tools_client=fake_tools_client(), places_client=FakeOSM(elements=elements).client(),
    )
    c = TestClient(app)
    c.__enter__()
    c.llm = llm
    return c


def test_when_nothing_is_near_the_circle_is_widened_and_the_person_is_told():
    c = town_app(FAR)
    try:
        h = login_guest(c)
        body = c.get(f"{P}/places/search", params={"city": "Guntur", "kind": "pharmacy", "radius_km": 5}, headers=h).json()
        assert len(body["items"]) == 3 and body["items"][0]["name"] == "Far Pharmacy"
        assert "Nothing was listed within 5 km, so this shows shops within 15 km" in body["note"]
    finally:
        c.__exit__(None, None, None)


def test_a_small_circle_that_already_has_shops_is_not_widened(shops):
    h = login_guest(shops)
    body = shops.get(f"{P}/places/search", params={"city": "Guntur", "kind": "pharmacy", "radius_km": 8}, headers=h).json()
    assert len(body["items"]) == 3 and "Nothing was listed" not in body["note"]


def test_the_assistant_widens_too_and_says_so():
    c = town_app(FAR)
    try:
        auth, _ = new_user(c)
        c.llm.script = [{"tool_calls": [("find_medical_shops", {"city": "Guntur", "radius_km": 5})]}, {"content": "The nearest is about 11 km away."}]
        ex = say(c, auth, "medical shop near me in Guntur")["tool_executions"][0]
        assert ex["status"] == "success" and len(ex["result"]["shops"]) == 3 and "within 15 km" in ex["result"]["note"]
    finally:
        c.__exit__(None, None, None)


def test_a_place_with_no_shops_at_all_gets_a_helpful_message():
    c = town_app([])
    try:
        auth, _ = new_user(c)
        c.llm.script = [{"tool_calls": [("find_medical_shops", {"city": "Guntur"})]}, {"content": "None listed."}]
        ex = say(c, auth, "medical shop in Guntur")["tool_executions"][0]
        assert ex["result"]["shops"] == [] and "No medical shops are listed within 25 km" in ex["result"]["note"]
    finally:
        c.__exit__(None, None, None)


def test_medical_stores_tagged_as_chemist_shops_are_found_but_beauty_shops_are_not():
    c = town_app([
        {"type": "node", "id": 9001, "lat": 16.3100, "lon": 80.4400, "tags": {"name": "Sri Lakshmi Medical Stores", "shop": "chemist"}},
        {"type": "node", "id": 9002, "lat": 16.3110, "lon": 80.4410, "tags": {"name": "Glow Beauty Zone", "shop": "chemist"}},
        {"type": "node", "id": 9003, "lat": 16.3120, "lon": 80.4420, "tags": {"name": "City Pharmacy", "amenity": "pharmacy"}},
    ])
    try:
        h = login_guest(c)
        names = [p["name"] for p in c.get(f"{P}/places/search", params={"city": "Guntur", "kind": "pharmacy", "radius_km": 8}, headers=h).json()["items"]]
        assert sorted(names) == ["City Pharmacy", "Sri Lakshmi Medical Stores"]
    finally:
        c.__exit__(None, None, None)
