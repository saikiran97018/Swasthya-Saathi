"""Google Maps (Places API, new) as the first source for clinics and medical shops, with OpenStreetMap as the automatic backup."""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services import scheduling as sched
from app.services.places import PlacesService
from tests.conftest import login_guest
from tests.fakes import FakeBhashini, FakeLLM, FakeOSM, fake_tools_client

P = "/api/v1"
KEY = "AIza-test-key-not-real"
ID1, ID2, ID3, ID4 = "ChIJ_apollo_pharmacy_1", "ChIJ_sai_medicals_two", "ChIJ_closed_shop_three", "ChIJ_clinic_four_abc"


def gplace(pid, name, lat, lon, types, **over):
    return {"id": pid, "displayName": {"text": name, "languageCode": "en"}, "formattedAddress": f"{name} Road, Guntur, Andhra Pradesh 522001, India",
            "location": {"latitude": lat, "longitude": lon}, "types": types, "googleMapsUri": f"https://maps.google.com/?cid={pid}", **over}


SHOPS = [
    gplace(ID1, "Apollo Pharmacy", 16.3080, 80.4380, ["pharmacy", "health", "store"], nationalPhoneNumber="086 32 000111", rating=4.4, userRatingCount=312,
           regularOpeningHours={"weekdayDescriptions": [f"{d}: 8:00 AM – 10:00 PM" for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]}),
    gplace(ID2, "Pradhan Mantri Jan Aushadhi Kendra", 16.3300, 80.4600, ["drugstore", "store"], businessStatus="OPERATIONAL"),
    gplace(ID3, "Shut Down Chemist", 16.3070, 80.4370, ["pharmacy"], businessStatus="CLOSED_PERMANENTLY"),
]
CLINICS = [gplace(ID4, "Dr Rao Family Clinic", 16.3100, 80.4400, ["doctor", "health"], nationalPhoneNumber="098480 12345")]


class FakeGoogle:
    def __init__(self, places=None, status=200):
        self.places, self.status = SHOPS if places is None else places, status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "Places API (New) has not been used in project 1 before or it is disabled."}})
        if request.method == "POST" and request.url.path.endswith("/places:searchNearby"):
            return httpx.Response(200, json={"places": self.places})
        if request.method == "GET" and "/places/" in request.url.path:
            pid = request.url.path.rsplit("/", 1)[1]
            hit = next((p for p in self.places if p["id"] == pid), None)
            return httpx.Response(200, json=hit) if hit else httpx.Response(404, json={})
        return httpx.Response(404, json={})


@contextmanager
def make(google: FakeGoogle, osm: FakeOSM | None = None, **settings):
    osm = osm or FakeOSM()

    def route(request: httpx.Request) -> httpx.Response:
        return google.handler(request) if request.url.host == "places.googleapis.com" else osm.handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(route))
    app = create_app(
        Settings(_env_file=None, bhashini_user_id="u", bhashini_ulca_api_key="k", reminder_poll_seconds=0, overpass_url="", places_request_gap_seconds=0, **settings),
        llm_client=FakeLLM([{"content": "ok"}]).client(), bhashini_client=FakeBhashini().client(), tools_client=fake_tools_client(), places_client=client,
    )
    with TestClient(app) as c:
        c.osm = osm
        yield c


def search(c, **params):
    return c.get(f"{P}/places/search", params={"city": "Guntur", **params}, headers=login_guest(c))


def mapped(body: dict) -> list[dict]:
    """The places from the map (the test database also holds demo partner clinics, which are listed first)."""
    return [p for p in body["items"] if p["source"] != "partner"]


def test_with_a_key_shops_come_from_google_nearest_first_and_closed_ones_are_left_out():
    g = FakeGoogle()
    with make(g, google_maps_api_key=KEY) as c:
        body = search(c, kind="pharmacy", radius_km=8).json()
    assert [p["name"] for p in body["items"]] == ["Apollo Pharmacy", "Pradhan Mantri Jan Aushadhi Kendra"]  # the closed shop is skipped
    first = body["items"][0]
    assert first["source"] == "google" and first["id"] == f"gmaps:{ID1}" and first["kind"] == "pharmacy" and first["rating"] == 4.4 and first["rating_count"] == 312
    assert first["maps_url"].startswith("https://maps.google.com/") and first["phone"] == "08632000111" and first["opening_hours"].endswith("8:00 AM – 10:00 PM")
    assert body["items"][1]["specialties"] == ["jan aushadhi"] and body["attribution"] == "Place data from Google Maps" and "Google Maps" in body["note"]
    assert c.osm.place_searches == 0  # OpenStreetMap was not needed


def test_the_request_to_google_is_well_formed_and_the_key_is_only_in_the_header():
    g = FakeGoogle()
    with make(g, google_maps_api_key=KEY) as c:
        search(c, kind="pharmacy", radius_km=8)
    req = next(r for r in g.requests if r.method == "POST")
    body = json.loads(req.content)
    assert req.headers["x-goog-api-key"] == KEY and "places.displayName" in req.headers["x-goog-fieldmask"] and KEY not in str(req.url)
    assert body["includedTypes"] == ["pharmacy", "drugstore"] and body["rankPreference"] == "DISTANCE" and body["maxResultCount"] == 20
    assert body["locationRestriction"]["circle"]["radius"] == 8000.0 and abs(body["locationRestriction"]["circle"]["center"]["latitude"] - 16.3067) < 0.01


def test_hospitals_and_doctors_use_google_too():
    with make(FakeGoogle(CLINICS), google_maps_api_key=KEY) as c:
        items = mapped(search(c).json())
    assert [p["name"] for p in items] == ["Dr Rao Family Clinic"] and items[0]["kind"] == "doctor" and items[0]["source"] == "google"


def test_when_google_fails_openstreetmap_answers_and_nobody_sees_an_error():
    g = FakeGoogle(status=403)  # for example "Places API (New)" not enabled for the key
    with make(g, google_maps_api_key=KEY) as c:
        r = search(c)
        body = r.json()
    assert r.status_code == 200 and len(mapped(body)) == 4 and all(p["source"] == "openstreetmap" for p in mapped(body))
    assert body["attribution"] == "Map data © OpenStreetMap contributors" and KEY not in r.text


def test_without_a_key_google_is_never_called():
    g = FakeGoogle()
    with make(g) as c:
        assert search(c).status_code == 200
    assert g.requests == []


def test_places_provider_osm_forces_openstreetmap_even_with_a_key():
    g = FakeGoogle()
    with make(g, google_maps_api_key=KEY, places_provider="osm") as c:
        search(c)
    assert g.requests == []


def test_an_empty_google_answer_also_falls_back_to_openstreetmap():
    with make(FakeGoogle([]), google_maps_api_key=KEY) as c:
        assert len(mapped(search(c).json())) == 4


def health(c) -> dict:
    return c.get(f"{P}/health").json()


def test_health_says_where_places_come_from_and_whether_google_works():
    with make(FakeGoogle(), google_maps_api_key=KEY) as c:
        assert health(c)["places_provider"] == "google" and health(c)["google_places_status"] == "untested"
        search(c, kind="pharmacy")
        assert health(c)["google_places_status"] == "ok"
    with make(FakeGoogle(status=403), google_maps_api_key=KEY) as c:
        search(c)
        h = health(c)
        assert h["places_provider"] == "google" and h["google_places_status"].startswith("error: HTTP 403") and "not been used" in h["google_places_status"] and KEY not in str(h)
    with make(FakeGoogle()) as c:
        assert health(c)["places_provider"] == "openstreetmap" and health(c)["google_places_status"] == "off"


def test_parse_skips_bad_rows():
    assert PlacesService.parse_google({"id": "short", "displayName": {"text": "x"}, "location": {"latitude": 1, "longitude": 2}}) is None  # a place id that is not one
    assert PlacesService.parse_google({"id": ID1, "displayName": {"text": ""}, "location": {"latitude": 1, "longitude": 2}}) is None
    assert PlacesService.parse_google({"id": ID1, "displayName": {"text": "A Shop"}}) is None
    temp = gplace(ID1, "Temp Closed", 16.3, 80.4, ["pharmacy"], businessStatus="CLOSED_TEMPORARILY")
    assert PlacesService.parse_google(temp) is None


def test_a_visit_can_be_planned_at_a_google_place():
    with make(FakeGoogle(CLINICS), google_maps_api_key=KEY) as c:
        h = login_guest(c)
        pid = mapped(c.get(f"{P}/places/search", params={"city": "Guntur"}, headers=h).json())[0]["id"]
        d = datetime.now(sched.IST).date() + timedelta(days=1)
        r = c.post(f"{P}/appointments", json={"place_id": pid, "slot_start": f"{d.isoformat()} 11:00", "patient_name": "Ravi Kumar", "patient_mobile": "9876543210", "reason": "fever"}, headers=h)
        assert r.status_code == 201, r.text
        a = r.json()
        assert a["clinic_confirmed"] is False and a["provider"]["name"] == "Dr Rao Family Clinic" and a["provider"]["code"].startswith("GM-") and len(a["provider"]["code"]) <= 24
        # the same place again reuses the same provider row
        r2 = c.post(f"{P}/appointments", json={"place_id": pid, "slot_start": f"{d.isoformat()} 15:00", "patient_name": "Ravi Kumar", "patient_mobile": "9876543210", "reason": "review"}, headers=h)
        assert r2.json()["provider"]["code"] == a["provider"]["code"]


def test_a_google_place_id_that_is_not_one_is_refused():
    with make(FakeGoogle(), google_maps_api_key=KEY) as c:
        h = login_guest(c)
        d = datetime.now(sched.IST).date() + timedelta(days=1)
        r = c.post(f"{P}/appointments", json={"place_id": "gmaps:../../etc", "slot_start": f"{d.isoformat()} 11:00", "patient_name": "Ravi Kumar", "patient_mobile": "9876543210", "reason": "x"}, headers=h)
        assert r.status_code in (400, 404, 422)
