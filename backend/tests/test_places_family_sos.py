"""Real places (OpenStreetMap, faked here), planned visits, family profiles, emergency contacts and the SOS screen."""
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.database.models import Reminder
from app.main import create_app
from app.services import scheduling as sched
from tests.conftest import login_guest
from tests.fakes import FakeBhashini, FakeLLM, FakeOSM, fake_tools_client
from tests.test_healthcare import book, run, say, tool_result

P = "/api/v1"
GGH = "osm:node/1001"  # Guntur General Hospital (hospital, two phone numbers)
SKIN = "osm:way/2002"  # Sri Skin & Care Clinic (a way: coordinates come from its centre)


@contextmanager
def make(osm: FakeOSM | None = None, llm: FakeLLM | None = None, demo: bool = False, overpass: bool = True, **settings):
    """overpass=True also configures the optional Overpass server; False = Nominatim only (the default in production)."""
    osm = osm or FakeOSM()
    llm = llm or FakeLLM([{"content": "ok"}])
    app = create_app(
        Settings(_env_file=None, bhashini_user_id="u", bhashini_ulca_api_key="k", reminder_poll_seconds=0, seed_demo_providers=demo,
                 overpass_url="https://overpass.test/api/interpreter" if overpass else "", places_request_gap_seconds=0, **settings),
        llm_client=llm.client(), bhashini_client=FakeBhashini().client(), tools_client=fake_tools_client(), places_client=osm.client(),
    )
    with TestClient(app) as c:
        c.osm, c.llm = osm, llm
        yield c


def visit_time(days=1, hour=11) -> str:
    d = datetime.now(sched.IST).date() + timedelta(days=days)
    return f"{d.isoformat()} {hour:02d}:00"


def plan(c, h, place=GGH, slot=None, **kw):
    body = {"place_id": place, "slot_start": slot or visit_time(), "patient_name": "Ravi Kumar", "patient_mobile": "9876543210", "reason": "fever and cold", **kw}
    return c.post(f"{P}/appointments", json=body, headers=h)


# =============================================================================== places search
def test_search_by_city_returns_real_places_nearest_first():
    with make() as c:
        h = login_guest(c)
        r = c.get(f"{P}/places/search", params={"city": "Guntur"}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["attribution"] == "Map data © OpenStreetMap contributors" and "OpenStreetMap" not in body["note"]
        assert body["center"]["label"].startswith("Guntur")
        names = [p["name"] for p in body["items"]]
        assert "Guntur General Hospital" in names and len(names) == 4  # the unnamed pin is skipped
        dist = [p["distance_km"] for p in body["items"]]
        assert dist == sorted(dist) and all(d >= 0 for d in dist)
        assert all(p["source"] == "openstreetmap" and p["has_slots"] is False and p["provider_code"] is None for p in body["items"])


def test_place_details_are_cleaned_and_classified():
    with make() as c:
        items = {p["id"]: p for p in c.get(f"{P}/places/search", params={"city": "Guntur"}, headers=login_guest(c)).json()["items"]}
        gh = items[GGH]
        assert gh["kind"] == "hospital" and gh["emergency"] is True
        assert gh["phone"] == "+918632222222"  # first of several numbers, spaces removed
        assert gh["website"] == "https://gghguntur.example.org" and gh["address"] == "Brodipet, Guntur"
        skin = items[SKIN]
        assert skin["kind"] == "clinic" and skin["specialties"] == ["dermatology"] and skin["opening_hours"] == "Mo-Sa 10:00-13:00"
        assert (skin["lat"], skin["lon"]) == (16.30, 80.43)  # taken from the way's centre
        assert items["osm:node/3003"]["kind"] == "doctor" and items["osm:node/3003"]["phone"] is None  # missing stays missing
        assert items["osm:node/5005"]["kind"] == "phc"


def test_search_by_gps_skips_geocoding():
    with make() as c:
        r = c.get(f"{P}/places/search", params={"lat": 16.3067, "lon": 80.4365, "radius_km": 5}, headers=login_guest(c))
        assert r.status_code == 200 and c.osm.geocodes == 0 and r.json()["center"]["lat"] == pytest.approx(16.3067)


def test_specialty_and_text_filters():
    with make() as c:
        h = login_guest(c)
        derm = c.get(f"{P}/places/search", params={"city": "Guntur", "specialty": "dermatology"}, headers=h).json()["items"]
        assert derm[0]["id"] == SKIN  # the matching clinic first ...
        assert GGH in [p["id"] for p in derm] and "osm:node/3003" not in [p["id"] for p in derm]  # ... hospitals kept, unrelated clinics dropped
        q = c.get(f"{P}/places/search", params={"city": "Guntur", "q": "rao"}, headers=h).json()["items"]
        assert [p["id"] for p in q] == ["osm:node/3003"]


def test_results_are_cached_so_openstreetmap_is_not_hammered():
    with make() as c:
        h = login_guest(c)
        for _ in range(3):
            assert c.get(f"{P}/places/search", params={"city": "Guntur"}, headers=h).status_code == 200
        assert c.osm.geocodes == 1 and c.osm.overpass_calls == 1
        assert all("SwasthyaSaathi" in ua for ua in c.osm.user_agents)  # the identifying User-Agent their policy asks for


def test_search_errors_are_clear():
    with make() as c:
        h = login_guest(c)
        assert c.get(f"{P}/places/search", headers=h).json()["error"]["code"] == "location_required"
        assert c.get(f"{P}/places/search", params={"lat": 16.3}, headers=h).json()["error"]["code"] == "location_required"
        assert c.get(f"{P}/places/search", params={"city": "Nowhereville"}, headers=h).status_code == 404
        assert c.get(f"{P}/places/search", params={"city": "Nowhereville"}, headers=h).json()["error"]["code"] == "place_not_found"
    with make(FakeOSM(down=True)) as c:
        r = c.get(f"{P}/places/search", params={"city": "Guntur"}, headers=login_guest(c))
        assert r.status_code == 502 and r.json()["error"]["code"] == "places_unavailable"


def test_nominatim_alone_gives_the_same_places_and_is_the_default():
    assert Settings.model_fields["overpass_url"].default == ""  # Overpass is opt-in: the public servers are often overloaded
    with make(overpass=False) as c:
        h = login_guest(c)
        body = c.get(f"{P}/places/search", params={"city": "Guntur"}, headers=h).json()
        names = {p["name"] for p in body["items"]}
        assert names == {"Guntur General Hospital", "Sri Skin & Care Clinic", "Dr. Rao Family Clinic", "Primary Health Centre Tenali Road"}
        assert c.osm.overpass_calls == 0 and c.osm.place_searches == 3  # one request each for hospital, clinic, doctors
        gh = next(p for p in body["items"] if p["id"] == GGH)
        assert gh["phone"] == "+918632222222" and gh["address"] == "Brodipet, Guntur" and gh["emergency"] is True
        assert next(p for p in body["items"] if p["id"] == SKIN)["specialties"] == ["dermatology"]
        c.get(f"{P}/places/search", params={"city": "Guntur"}, headers=h)
        assert c.osm.place_searches == 3  # cached


def test_kind_filter_is_honoured_by_nominatim():
    with make(overpass=False) as c:
        hospitals = c.get(f"{P}/places/search", params={"city": "Guntur", "kind": "hospital"}, headers=login_guest(c)).json()["items"]
        assert [p["kind"] for p in hospitals] == ["hospital"] and c.osm.place_searches == 1


def test_when_overpass_is_down_nominatim_still_answers():
    with make(FakeOSM(overpass_down=True)) as c:
        r = c.get(f"{P}/places/search", params={"city": "Guntur"}, headers=login_guest(c))
        assert r.status_code == 200 and len(r.json()["items"]) == 4 and c.osm.overpass_calls >= 1


def test_a_place_can_be_planned_even_if_the_server_restarted_since_the_search():
    """place_id comes from a search made earlier; a cold cache must look the place up again (Nominatim /lookup)."""
    with make(overpass=False) as c:
        r = plan(c, login_guest(c), place=SKIN)
        assert r.status_code == 201 and r.json()["provider"]["name"] == "Sri Skin & Care Clinic" and c.osm.lookups == 1


def test_overpass_query_contains_only_numbers_from_the_user():
    with make() as c:
        c.get(f"{P}/places/search", params={"city": "Guntur", "q": 'x"];out;'}, headers=login_guest(c))
        assert 'x"];out' not in c.osm.queries[0]  # free text never reaches the Overpass query


def test_no_sample_clinics_exist_unless_explicitly_enabled():
    assert Settings.model_fields["seed_demo_providers"].default is False and Settings.model_fields["demo_mode"].default is False  # (tests override via env)
    with make() as c:
        listing = c.get(f"{P}/providers", headers=login_guest(c)).json()
        assert (listing if isinstance(listing, list) else listing.get("items", [])) == []
    with make(demo=True) as c:
        assert c.get(f"{P}/places/search", params={"city": "Guntur"}, headers=login_guest(c)).json()["items"][0]["source"] == "partner"


# =============================================================================== planned visits
def test_planning_a_visit_at_a_real_place():
    with make() as c:
        h = login_guest(c)
        r = plan(c, h)
        assert r.status_code == 201, r.text
        a = r.json()
        assert a["clinic_confirmed"] is False and a["status"] == "booked" and a["patient_mobile"] == "98XXXXXX10"
        prov = a["provider"]
        assert prov["source"] == "osm" and prov["name"] == "Guntur General Hospital" and prov["phone"] == "+918632222222" and prov["code"] == "OSM-N1001"
        assert prov["fee_inr"] == 0 and prov["is_demo"] is False
        assert [x["ref"] for x in c.get(f"{P}/appointments", headers=h).json()["items"]] == [a["ref"]]


def test_planned_visit_time_rules():
    with make() as c:
        h = login_guest(c)
        soon = (datetime.now(sched.IST) + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
        r = plan(c, h, slot=soon)
        err = r.json()["error"]
        assert r.status_code == 400 and err["code"] == "slot_in_past" and "2 hours" in err["message"] and "earliest time you can plan" in err["message"]
        # the message names a time the user can actually book, and that exact time is accepted
        from app.services.appointments import AppointmentService

        svc = AppointmentService(None, c.app.state.settings)  # earliest_visit_time needs no database
        ok_time = svc.earliest_visit_time().strftime("%Y-%m-%d %H:%M")
        assert plan(c, h, slot=ok_time).status_code == 201
        far = (datetime.now(sched.IST) + timedelta(days=90)).strftime("%Y-%m-%d 11:00")
        assert plan(c, h, slot=far).json()["error"]["code"] == "slot_too_far"
        assert plan(c, h, mode="teleconsultation").json()["error"]["code"] == "no_teleconsultation"
        assert plan(c, h, slot="tomorrow").json()["error"]["code"] == "invalid_slot"
        assert plan(c, h, patient_mobile="1234567890").json()["error"]["code"] == "invalid_mobile"  # 10 digits, but not a valid Indian mobile


def test_earliest_visit_time_is_always_accepted_and_never_early():
    from datetime import timezone

    from app.services.appointments import AppointmentService

    svc = AppointmentService(None, Settings(_env_file=None))
    for hour, minute, second in [(10, 8, 0), (10, 8, 30), (10, 10, 0), (10, 9, 59), (23, 55, 1)]:
        now = datetime(2026, 11, 21, hour, minute, second, tzinfo=sched.IST).astimezone(timezone.utc)
        earliest = svc.earliest_visit_time(now)
        assert earliest >= now + timedelta(minutes=121 - 1) and earliest.minute % 10 == 0 and earliest.second == 0
        svc._validate_visit_time(earliest, now + timedelta(seconds=45))  # still valid a moment later (no exception)
    # the very case from the field: it is 10:08, so "12:00" is too early and the message names the right time
    now = datetime(2026, 11, 21, 10, 8, tzinfo=sched.IST).astimezone(timezone.utc)
    from app.services.appointments import BookingError

    with pytest.raises(BookingError) as exc:
        svc._validate_visit_time(datetime(2026, 11, 21, 12, 0, tzinfo=sched.IST), now)
    assert "12:10 PM" in exc.value.message and "2 hours" in exc.value.message


def test_exactly_one_of_provider_code_or_place_id():
    with make(demo=True) as c:
        h = login_guest(c)
        base = {"slot_start": visit_time(), "patient_name": "Ravi Kumar", "patient_mobile": "9876543210", "reason": "fever"}
        assert c.post(f"{P}/appointments", json=base, headers=h).status_code == 422
        assert c.post(f"{P}/appointments", json={**base, "place_id": GGH, "provider_code": "HC-GNT-01"}, headers=h).status_code == 422
        assert c.post(f"{P}/appointments", json={**base, "place_id": "osm:node/999999"}, headers=h).json()["error"]["code"] == "place_not_found"
        assert c.post(f"{P}/appointments", json={**base, "place_id": "not-an-id"}, headers=h).json()["error"]["code"] == "place_not_found"


def test_two_people_can_plan_the_same_time_at_the_same_place():
    """A planned visit is only the user's own note: it must never block someone else (unlike a clinic-confirmed slot)."""
    with make() as c:
        a, b = login_guest(c), login_guest(c)
        slot = visit_time()
        assert plan(c, a, slot=slot).status_code == 201
        assert plan(c, b, slot=slot).status_code == 201


def test_a_person_cannot_plan_two_overlapping_visits():
    with make() as c:
        h = login_guest(c)
        assert plan(c, h).status_code == 201
        r = plan(c, h, place=SKIN)
        assert r.status_code == 400 and r.json()["error"]["code"] == "user_conflict"


def test_planned_visit_can_be_cancelled_and_rescheduled_by_the_agent():
    with make() as c:
        h = login_guest(c)
        ref = plan(c, h).json()["ref"]
        llm = c.llm
        llm.script = [{"tool_calls": [("reschedule_appointment", {"reference": ref, "new_slot_start": visit_time(days=3, hour=15)})]}]
        first = say(c, h, "move it")
        llm.script = [{"content": "moved"}]
        done = c.post(f"{P}/agents/executions/{first['pending_confirmation']['id']}/confirm", json={"approve": True}, headers=h).json()
        assert tool_result(done)["status"] == "success"
        appt = c.get(f"{P}/appointments", headers=h).json()["items"][0]
        assert appt["reschedule_count"] == 1 and appt["clinic_confirmed"] is False
        assert c.post(f"{P}/appointments/{appt['id']}/cancel", json={}, headers=h).json()["status"] == "cancelled"


def test_reminders_for_a_planned_visit_say_it_is_not_confirmed():
    with make() as c:
        h = login_guest(c)
        plan(c, h, slot=visit_time(days=3))
        rows = run(c, lambda s: s.scalars(select(Reminder).where(Reminder.kind == "appointment_reminder")))
        texts = [r.message for r in run(c, lambda s: _all(s))]
        assert texts and all("not confirmed" in t and "phone" in t.lower() or "call" in t.lower() for t in texts)
        assert rows is not None


async def _all(session):
    return list((await session.scalars(select(Reminder).where(Reminder.kind == "appointment_reminder"))).all())


def test_partner_slots_are_still_confirmed_and_still_protected_from_double_booking():
    with make(demo=True) as c:
        a, b = login_guest(c), login_guest(c)
        start = (datetime.now(sched.IST).date() + timedelta(days=1)).isoformat()
        slot = next(f"{d} {t}" for d, ts in c.get(f"{P}/providers/HC-GNT-01/availability?from_date={start}&days=7", headers=a).json()["open_slots"].items() for t in ts)
        body = {"provider_code": "HC-GNT-01", "slot_start": slot, "patient_name": "Ravi Kumar", "patient_mobile": "9876543210", "reason": "fever"}
        first = c.post(f"{P}/appointments", json=body, headers=a)
        assert first.status_code == 201 and first.json()["clinic_confirmed"] is True
        assert c.post(f"{P}/appointments", json=body, headers=b).json()["error"]["code"] == "slot_taken"


# =============================================================================== the agent with real places
def test_agent_finds_real_places_and_plans_a_visit():
    with make() as c:
        h = login_guest(c)
        llm = c.llm
        llm.script = [{"tool_calls": [("find_healthcare_providers", {"specialty": "dermatology", "city": "Guntur"})]}, {"content": "Here are places."}]
        found = tool_result(say(c, h, "skin doctor in Guntur"))["result"]
        codes = [r["code"] for r in found["results"]]
        assert codes[0] == "OSM-W2002" and all(r["bookable_online"] is False for r in found["results"])
        assert "OpenStreetMap" in found["note"] and "fee_inr" not in found["results"][0]

        llm.script = [{"tool_calls": [("check_availability", {"provider_code": "OSM-W2002"})]}, {"content": "No online slots."}]
        avail = tool_result(say(c, h, "when is it free?"))["result"]
        assert avail["bookable_online"] is False and "PLANNED" in avail["note"] and "08632111111" in avail["note"]

        pend, out = book(c, h, llm, visit_time(days=2, hour=10), code="OSM-W2002", reason="itchy skin rash")
        assert "PLANNED" in pend["explanation"] and "NOT confirmed" in pend["explanation"].replace("has NOT confirmed", "NOT confirmed")
        result = tool_result(out)
        assert result["status"] == "success" and result["result"]["clinic_confirmed"] is False and "NOT confirmed" in result["result"]["important"]
        assert c.get(f"{P}/appointments", headers=h).json()["items"][0]["clinic_confirmed"] is False


def test_agent_reports_a_map_outage_instead_of_inventing_places():
    with make(FakeOSM(down=True)) as c:
        h = login_guest(c)
        c.llm.script = [{"tool_calls": [("find_healthcare_providers", {"city": "Guntur"})]}, {"content": "The map is down."}]
        res = tool_result(say(c, h, "doctor in Guntur"))["result"]
        assert res["results"] == [] and "Could not look up" in res["note"]


# =============================================================================== family profiles
def member(c, h, **kw):
    body = {"name": "Asha Devi", "relation": "parent", "birth_year": 1960, "gender": "female", "mobile": "98480 12345", "language": "te", **kw}
    return c.post(f"{P}/family", json=body, headers=h)


def test_family_crud_and_isolation():
    with make() as c:
        h, other = login_guest(c), login_guest(c)
        r = member(c, h)
        assert r.status_code == 201, r.text
        m = r.json()
        assert m["name"] == "Asha Devi" and m["mobile"] == "9848012345" and m["language"] == "te" and m["relation"] == "parent"
        assert [x["id"] for x in c.get(f"{P}/family", headers=h).json()] == [m["id"]] and c.get(f"{P}/family", headers=other).json() == []
        upd = c.patch(f"{P}/family/{m['id']}", json={"name": "  Asha   D  ", "birth_year": 1961, "mobile": None}, headers=h).json()
        assert upd["name"] == "Asha D" and upd["birth_year"] == 1961 and upd["mobile"] is None and upd["language"] == "te"  # untouched fields stay
        assert c.patch(f"{P}/family/{m['id']}", json={"name": "Hacker"}, headers=other).status_code == 404
        assert c.delete(f"{P}/family/{m['id']}", headers=other).status_code == 404
        assert c.delete(f"{P}/family/{m['id']}", headers=h).status_code == 204 and c.get(f"{P}/family", headers=h).json() == []


def test_family_validation_and_limit():
    with make() as c:
        h = login_guest(c)
        assert member(c, h, mobile="123").json()["error"]["code"] == "invalid_mobile"
        assert member(c, h, language="xx").json()["error"]["code"] == "unsupported_language"
        assert member(c, h, name="A").status_code == 422 and member(c, h, birth_year=datetime.now().year + 1).status_code == 422
        assert member(c, h, relation="friend").status_code == 422
        for i in range(8):
            assert member(c, h, name=f"Person {i}").status_code == 201
        r = member(c, h, name="One too many")
        assert r.status_code == 409 and r.json()["error"]["code"] == "family_limit"


def test_booking_for_a_family_member_and_per_person_conflicts():
    with make() as c:
        h = login_guest(c)
        mom, kid = member(c, h).json(), member(c, h, name="Little Ravi", relation="child", birth_year=2018).json()
        slot = visit_time()
        mine = plan(c, h, slot=slot)
        assert mine.status_code == 201 and mine.json()["family_member"] is None
        for_mom = plan(c, h, place=SKIN, slot=slot, patient_name="Asha Devi", family_member_id=mom["id"])
        assert for_mom.status_code == 201, for_mom.text  # same time as the account holder's own visit: different person, no clash
        assert for_mom.json()["family_member"] == {"id": mom["id"], "name": "Asha Devi", "relation": "parent"}
        assert plan(c, h, place="osm:node/3003", slot=slot, patient_name="Little Ravi", family_member_id=kid["id"]).status_code == 201
        again = plan(c, h, place="osm:node/5005", slot=slot, patient_name="Asha Devi", family_member_id=mom["id"])
        assert again.status_code == 400 and again.json()["error"]["code"] == "user_conflict" and "Asha Devi already has" in again.json()["error"]["message"]


def test_cannot_book_for_someone_elses_family_member():
    with make() as c:
        h, other = login_guest(c), login_guest(c)
        theirs = member(c, other).json()
        r = plan(c, h, family_member_id=theirs["id"])
        assert r.status_code == 404 and r.json()["error"]["code"] == "family_member_not_found"


def test_deleting_a_member_keeps_their_past_appointments():
    with make() as c:
        h = login_guest(c)
        m = member(c, h).json()
        appt = plan(c, h, patient_name="Asha Devi", family_member_id=m["id"]).json()
        assert c.delete(f"{P}/family/{m['id']}", headers=h).status_code == 204
        kept = c.get(f"{P}/appointments", headers=h).json()["items"][0]
        assert kept["ref"] == appt["ref"] and kept["patient_name"] == "Asha Devi" and kept["family_member"] is None


def test_agent_links_a_booking_to_a_saved_family_member_and_knows_the_names():
    with make() as c:
        h = login_guest(c)
        m = member(c, h).json()
        llm = c.llm
        llm.script = [{"content": "hi"}]
        say(c, h, "hello")
        system = next(r for r in llm.requests if r.get("stream"))["messages"][0]["content"]
        assert "Saved family members: Asha Devi (parent)" in system
        llm.script = [{"tool_calls": [("find_healthcare_providers", {"city": "Guntur"})]}, {"content": "Here are places."}]
        say(c, h, "doctor in Guntur")  # finding places is what makes their codes bookable
        pend, out = book(c, h, llm, visit_time(), code="OSM-N1001", name="asha devi", mobile="9848012345")
        assert tool_result(out)["status"] == "success"
        assert c.get(f"{P}/appointments", headers=h).json()["items"][0]["family_member"]["id"] == m["id"]


# =============================================================================== emergency contacts & SOS
def test_emergency_contacts_crud_limit_and_isolation():
    with make() as c:
        h, other = login_guest(c), login_guest(c)
        r = c.post(f"{P}/emergency-contacts", json={"name": "Lakshmi", "phone": "+91 98480 12345", "relation": " sister "}, headers=h)
        assert r.status_code == 201 and r.json()["phone"] == "9848012345" and r.json()["relation"] == "sister"
        cid = r.json()["id"]
        assert c.get(f"{P}/emergency-contacts", headers=other).json() == []
        assert c.post(f"{P}/emergency-contacts", json={"name": "Bad", "phone": "12345"}, headers=h).json()["error"]["code"] == "invalid_mobile"
        assert c.delete(f"{P}/emergency-contacts/{cid}", headers=other).status_code == 404
        for i in range(4):
            assert c.post(f"{P}/emergency-contacts", json={"name": f"Friend {i}", "phone": f"98480000{i:02d}"}, headers=h).status_code == 201
        r = c.post(f"{P}/emergency-contacts", json={"name": "Sixth", "phone": "9848000099"}, headers=h)
        assert r.status_code == 409 and r.json()["error"]["code"] == "contact_limit"
        assert c.delete(f"{P}/emergency-contacts/{cid}", headers=h).status_code == 204


def test_sos_always_has_numbers_and_first_aid():
    with make() as c:
        body = c.get(f"{P}/sos", headers=login_guest(c)).json()
        codes = {n["code"] for n in body["numbers"]}
        assert {"112", "108", "181", "1098", "14416"} <= codes
        assert body["nearby"] == [] and "does not call" in body["disclaimer"]
        cards = {f["id"]: f for f in body["first_aid"]}
        assert {"chest_pain", "not_breathing", "bleeding", "choking", "burns", "stroke", "snakebite"} <= set(cards)
        text = " ".join(" ".join(f["steps"]) for f in cards.values()).lower()
        assert all(f["steps"] and f["call_if"] for f in cards.values())
        for banned in ("aspirin", "paracetamol", " mg", "tourniquet is", "suck the"):  # no medicines or doses, ever
            assert banned not in text


def test_sos_lists_nearby_hospitals_from_a_city_or_gps_and_survives_a_map_outage():
    with make() as c:
        h = login_guest(c)
        near = c.get(f"{P}/sos", params={"city": "Guntur"}, headers=h).json()["nearby"]
        assert near and all(n["source"] == "openstreetmap" and n["kind"] == "hospital" for n in near) and near[0]["name"] == "Guntur General Hospital"
        assert near[0]["phone"] == "+918632222222" and near[0]["distance_km"] is not None
        assert c.get(f"{P}/sos", params={"lat": 16.3, "lon": 80.43}, headers=h).json()["nearby"]
    with make(FakeOSM(down=True)) as c:  # the screen must never fail when someone needs it
        r = c.get(f"{P}/sos", params={"city": "Guntur"}, headers=login_guest(c))
        assert r.status_code == 200 and r.json()["nearby"] == [] and r.json()["numbers"]
