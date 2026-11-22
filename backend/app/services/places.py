"""Real hospitals and clinics from OpenStreetMap (no API key, no invented data).

* Nominatim turns a city name into coordinates.
* Overpass lists hospitals / clinics / doctors around a point.

OpenStreetMap is community-edited: names, phone numbers and opening hours are present only when someone added them, and
there is NO appointment system behind these places. So a place never has slots: the app can show it, help the user call
or navigate to it, and record a visit the user PLANS (which the clinic has not confirmed).
Both services are public and rate limited, so results are cached and the identifying User-Agent is sent as their policy asks.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import datetime, timedelta, timezone
import logging
import math
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import NotFound, ServiceUnavailable, UpstreamError

log = logging.getLogger("app.places")

ATTRIBUTION = "Map data © OpenStreetMap contributors"
GOOGLE_ATTRIBUTION = "Place data from Google Maps"
_ID_RE = re.compile(r"^osm:(node|way|relation)/(\d{1,14})$")
_GOOGLE_ID_RE = re.compile(r"^gmaps:[A-Za-z0-9_-]{10,34}$")
_SPECIALTY_WORDS = {  # name keywords -> our specialty names (only used when the place has no speciality tag)
    "dermatology": ("derma", "skin"),
    "dentistry": ("dental", "dentist", "teeth"),
    "ophthalmology": ("eye", "ophthal", "netra"),
    "ent": (" ent ", "ear nose", "ent clinic", "ent hospital"),
    "orthopedics": ("ortho", "bone", "joint"),
    "cardiology": ("cardi", "heart"),
    "pediatrics": ("child", "paediat", "pediat", "kids", "baby"),
    "gynecology": ("gyn", "maternity", "women", "obstet", "fertility"),
    "psychiatry": ("psychi", "mental", "mind"),
}
_TAG_TO_SPECIALTY = {
    "dermatology": "dermatology", "dermatology_venereology": "dermatology", "dentist": "dentistry", "dentistry": "dentistry",
    "ophthalmology": "ophthalmology", "otolaryngology": "ent", "ent": "ent", "orthopaedics": "orthopedics", "orthopedics": "orthopedics",
    "cardiology": "cardiology", "paediatrics": "pediatrics", "pediatrics": "pediatrics", "gynaecology": "gynecology",
    "gynecology": "gynecology", "obstetrics": "gynecology", "psychiatry": "psychiatry", "general": "general medicine",
    "general_practice": "general medicine", "internal": "general medicine", "family_medicine": "general medicine",
}


@dataclass(frozen=True)
class Place:
    id: str  # "osm:node/123"
    name: str
    kind: str  # hospital | clinic | doctor | phc | pharmacy | other
    lat: float
    lon: float
    specialties: list[str] = field(default_factory=list)
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    website: str | None = None
    opening_hours: str | None = None
    emergency: bool = False
    distance_km: float | None = None
    rating: float | None = None  # Google only
    rating_count: int | None = None
    maps_url: str | None = None  # Google Maps page of the place

    @property
    def is_google(self) -> bool:
        return self.id.startswith("gmaps:")

    @property
    def osm_key(self) -> str:
        """Unique key stored on the provider row: 'node/123' for OpenStreetMap, 'gmaps/<id>' for Google."""
        return "gmaps/" + self.id[6:] if self.is_google else self.id.removeprefix("osm:")

    @property
    def provider_code(self) -> str:
        """Short speakable code that fits Provider.code, e.g. OSM-N123456 (N = node, W = way, R = relation)."""
        if self.is_google:
            return "GM-" + base64.b32encode(hashlib.sha1(self.id.encode()).digest())[:8].decode()
        kind, num = self.osm_key.split("/")
        return f"OSM-{kind[0].upper()}{num}"


@dataclass
class SearchResult:
    center: tuple[float, float, str | None]
    places: list[Place]
    truncated: bool = False


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _clean(text: str | None, limit: int = 300) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split())
    return text[:limit] or None


def _phone(tags: dict[str, str]) -> str | None:
    raw = tags.get("phone") or tags.get("contact:phone") or tags.get("contact:mobile") or tags.get("mobile")
    if not raw:
        return None
    first = re.split(r"[;,/]", raw)[0].strip()  # OSM often holds several numbers separated by ';'
    digits = re.sub(r"[^\d+]", "", first)
    return digits if 6 <= len(digits.lstrip("+")) <= 15 else None


def _website(tags: dict[str, str]) -> str | None:
    url = (tags.get("website") or tags.get("contact:website") or "").strip()
    if not url:
        return None
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url[:300] if re.match(r"^https?://[^\s]+$", url, re.I) else None


def _address(tags: dict[str, str]) -> tuple[str | None, str | None]:
    full = _clean(tags.get("addr:full"))
    city = _clean(tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village") or tags.get("addr:suburb"), 80)
    if full:
        return full, city
    parts = [tags.get(k) for k in ("addr:housenumber", "addr:street", "addr:suburb", "addr:city", "addr:postcode")]
    line = ", ".join(p.strip() for p in parts if p and p.strip())
    return (line[:300] or None), city


def _kind(tags: dict[str, str], name: str) -> str:
    amenity, healthcare = tags.get("amenity", ""), tags.get("healthcare", "")
    low = name.lower()
    if re.search(r"primary health|\bphc\b|health cent(re|er)|sub.?cent(re|er)|arogya mandir|community health", low):
        return "phc"
    if amenity == "pharmacy" or healthcare == "pharmacy" or (tags.get("shop") == "chemist" and _MEDICAL_SHOP_NAME.search(name)):
        return "pharmacy"
    if amenity == "hospital" or healthcare == "hospital":
        return "hospital"
    if amenity == "doctors" or healthcare in ("doctor", "doctors"):
        return "doctor"
    if amenity == "clinic" or healthcare in ("clinic", "centre"):
        return "clinic"
    return "other"


def _specialties(tags: dict[str, str], name: str) -> list[str]:
    out: list[str] = []
    for raw in (tags.get("healthcare:speciality") or tags.get("healthcare:specialty") or "").split(";"):
        mapped = _TAG_TO_SPECIALTY.get(raw.strip().lower().replace(" ", "_"))
        if mapped and mapped not in out:
            out.append(mapped)
    if not out:  # no tag: a conservative guess from the name only
        low = f" {name.lower()} "
        for spec, words in _SPECIALTY_WORDS.items():
            if any(w in low for w in words):
                out.append(spec)
    return out


_AMENITY = {"hospital": "hospital", "clinic": "clinic", "doctor": "doctors", "pharmacy": "pharmacy", None: "hospital|clinic|doctors"}
_HEALTHCARE = {"hospital": "hospital", "clinic": "clinic|centre", "doctor": "doctor", "pharmacy": "pharmacy", None: "hospital|clinic|doctor|centre"}
_MEDICAL_SHOP_NAME = re.compile(r"medic|pharm|chemist|drug|dawa|davai|aushadhi|apollo|medplus|health|care", re.I)  # keeps beauty / toiletry shops out
_JAN_AUSHADHI = re.compile(r"jan\s*aushadhi|janaushadhi|pmbjp|pradhan mantri bharatiya jan", re.I)


def _nearby_query(lat: float, lon: float, radius_m: int, kind: str | None) -> str:
    """Overpass QL: named-or-not hospitals / clinics / doctors around a point (nodes, ways and relations)."""
    around = f"(around:{radius_m},{float(lat)},{float(lon)})"  # floats only: nothing user-typed ever reaches the query text
    return (
        "[out:json][timeout:25];("
        f'nwr["amenity"~"^({_AMENITY[kind]})$"]{around};'
        f'nwr["healthcare"~"^({_HEALTHCARE[kind]})$"]{around};'
        + (f'nwr["shop"="chemist"]{around};' if kind == "pharmacy" else "")
        + ");out center tags 300;"
    )


def parse_element(el: dict[str, Any]) -> Place | None:
    tags: dict[str, str] = el.get("tags") or {}
    name = _clean(tags.get("name:en") or tags.get("name"), 200)
    kind_type = el.get("type")
    if not name or kind_type not in ("node", "way", "relation") or not isinstance(el.get("id"), int):
        return None  # an unnamed pin is no use to a patient
    lat = el.get("lat") if kind_type == "node" else (el.get("center") or {}).get("lat")
    lon = el.get("lon") if kind_type == "node" else (el.get("center") or {}).get("lon")
    if lat is None or lon is None:
        return None
    address, city = _address(tags)
    kind = _kind(tags, name)
    specs = (["jan aushadhi"] if _JAN_AUSHADHI.search(name) else []) if kind == "pharmacy" else _specialties(tags, name)  # a chemist has no medical specialty
    return Place(
        id=f"osm:{kind_type}/{el['id']}", name=name, kind=kind, lat=float(lat), lon=float(lon), specialties=specs,
        address=address, city=city, phone=_phone(tags), website=_website(tags), opening_hours=_clean(tags.get("opening_hours")),
        emergency=tags.get("emergency") == "yes" or kind == "hospital",
    )


_NOMINATIM_TERMS = {"hospital": ["hospital"], "clinic": ["clinic"], "doctor": ["doctors"], "pharmacy": ["pharmacy", "chemist"], None: ["hospital", "clinic", "doctors"]}
_ADDR_KEYS = {"house_number": "addr:housenumber", "road": "addr:street", "suburb": "addr:suburb", "postcode": "addr:postcode"}


def parse_nominatim(row: dict[str, Any]) -> Place | None:
    """One Nominatim result (addressdetails + extratags + namedetails) -> Place, by rebuilding OpenStreetMap-style tags."""
    otype, oid = row.get("osm_type"), row.get("osm_id")
    if otype not in ("node", "way", "relation") or not isinstance(oid, int):
        return None
    tags: dict[str, str] = {str(k): str(v) for k, v in (row.get("extratags") or {}).items()}
    names = row.get("namedetails") or {}
    tags["name"] = names.get("name:en") or names.get("name") or row.get("name") or ""
    if row.get("category") == "amenity":
        tags["amenity"] = str(row.get("type", ""))
    elif row.get("category") == "healthcare":
        tags["healthcare"] = str(row.get("type", ""))
    elif row.get("category") == "shop":
        tags["shop"] = str(row.get("type", ""))
    addr = row.get("address") or {}
    for src, dst in _ADDR_KEYS.items():
        if addr.get(src):
            tags.setdefault(dst, str(addr[src]))
    town = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality")
    if town:
        tags.setdefault("addr:city", str(town))
    try:
        lat, lon = float(row["lat"]), float(row["lon"])
    except (KeyError, ValueError, TypeError):
        return None
    element: dict[str, Any] = {"type": otype, "id": oid, "tags": tags}
    element.update({"lat": lat, "lon": lon} if otype == "node" else {"center": {"lat": lat, "lon": lon}})
    return parse_element(element)


class PlacesService:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.s, self.http = settings, http
        self._geo: dict[str, tuple[float, float, str | None, float]] = {}
        self._near: dict[tuple[float, float, int, str], tuple[list[Place], float]] = {}
        self._by_id: dict[str, tuple[Place, float]] = {}

    # ------------------------------------------------------------------ helpers
    @property
    def _headers(self) -> dict[str, str]:
        return {"User-Agent": "SwasthyaSaathi/1.0 (health access assistant)", "Accept-Language": "en"}

    def _require(self) -> None:
        if not self.s.places_enabled:
            raise ServiceUnavailable("Finding nearby places is switched off (PLACES_ENABLED=false).", code="places_disabled")

    def _fresh(self, stamp: float) -> bool:
        return time.time() - stamp < self.s.places_cache_seconds

    # ------------------------------------------------------------------ city -> coordinates
    async def geocode(self, city: str) -> tuple[float, float, str | None]:
        self._require()
        key = " ".join(city.lower().split())
        if not key:
            raise NotFound("Tell me a city or town.", code="place_not_found")
        hit = self._geo.get(key)
        if hit and self._fresh(hit[3]):
            return hit[0], hit[1], hit[2]
        try:
            resp = await self.http.get(
                self.s.nominatim_url, params={"q": city, "format": "jsonv2", "limit": 1, "countrycodes": "in", "accept-language": "en"},
                headers=self._headers, timeout=self.s.places_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not reach the map service to find that place. Please try again.", retryable=True, code="places_unavailable") from exc
        if resp.status_code != 200:
            raise UpstreamError("The map service is busy. Please try again in a moment.", retryable=resp.status_code >= 500 or resp.status_code == 429, code="places_unavailable")
        try:
            rows = resp.json()
            lat, lon, label = float(rows[0]["lat"]), float(rows[0]["lon"]), _clean(rows[0].get("display_name"), 200)
        except (ValueError, KeyError, IndexError, TypeError):
            raise NotFound(f"I could not find '{city}' in India. Check the spelling or try the nearest big town.", code="place_not_found") from None
        self._geo[key] = (lat, lon, label, time.time())
        return lat, lon, label

    # ------------------------------------------------------------------ Nominatim as a place list (the main source)
    @property
    def _lookup_url(self) -> str:
        return re.sub(r"/search/?$", "/lookup", self.s.nominatim_url)

    async def _nominatim_get(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            resp = await self.http.get(url, params=params, headers=self._headers, timeout=self.s.places_timeout_seconds)
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not reach the map service. Please try again.", retryable=True, code="places_unavailable") from exc
        if resp.status_code != 200:
            raise UpstreamError("The map service is busy. Please try again in a moment.", retryable=resp.status_code >= 500 or resp.status_code == 429, code="places_unavailable")
        try:
            rows = resp.json()
        except ValueError as exc:
            raise UpstreamError("The map service sent an unreadable answer.", retryable=True, code="places_unavailable") from exc
        return rows if isinstance(rows, list) else []

    async def _nominatim_nearby(self, lat: float, lon: float, radius_km: float, kind: str | None) -> list[Place]:
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
        viewbox = f"{lon - dlon},{lat + dlat},{lon + dlon},{lat - dlat}"  # left, top, right, bottom
        wanted = {"hospital": ("hospital",), "clinic": ("clinic", "phc"), "doctor": ("doctor",), "pharmacy": ("pharmacy",)}.get(kind or "")
        seen: dict[str, Place] = {}
        for i, term in enumerate(_NOMINATIM_TERMS[kind]):
            if i and self.s.places_request_gap_seconds:
                await asyncio.sleep(self.s.places_request_gap_seconds)
            rows = await self._nominatim_get(self.s.nominatim_url, {
                "q": term, "format": "jsonv2", "limit": 40, "countrycodes": "in", "viewbox": viewbox, "bounded": 1,
                "addressdetails": 1, "extratags": 1, "namedetails": 1, "accept-language": "en",
            })
            for row in rows:
                place = parse_nominatim(row)
                if place and (wanted is None or place.kind in wanted):
                    seen.setdefault(place.id, place)
        return list(seen.values())

    # ------------------------------------------------------------------ Google Places (New)
    _G_TYPES = {"hospital": ["hospital"], "clinic": ["doctor"], "doctor": ["doctor"], "pharmacy": ["pharmacy", "drugstore"], None: ["hospital", "doctor"]}
    _G_FIELDS = (
        "places.id,places.displayName,places.formattedAddress,places.location,places.nationalPhoneNumber,places.regularOpeningHours.weekdayDescriptions,"
        "places.websiteUri,places.googleMapsUri,places.rating,places.userRatingCount,places.types,places.businessStatus"
    )

    def _g_headers(self, fields: str) -> dict[str, str]:
        return {"X-Goog-Api-Key": self.s.google_maps_api_key, "X-Goog-FieldMask": fields, "Content-Type": "application/json"}

    @staticmethod
    def parse_google(p: dict[str, Any]) -> Place | None:
        pid, loc = p.get("id"), p.get("location") or {}
        name = _clean((p.get("displayName") or {}).get("text"), 200)
        if not pid or not name or "latitude" not in loc or "longitude" not in loc or not re.match(r"^[A-Za-z0-9_-]{10,34}$", str(pid)):
            return None
        if p.get("businessStatus") in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
            return None  # a patient must not be sent to a shop that has shut
        types = set(p.get("types") or [])
        if "pharmacy" in types or "drugstore" in types:
            kind = "pharmacy"
        elif re.search(r"primary health|\bphc\b|health cent(re|er)|sub.?cent(re|er)|arogya mandir|community health", name.lower()):
            kind = "phc"
        elif "hospital" in types:
            kind = "hospital"
        elif "doctor" in types:
            kind = "doctor"
        else:
            kind = "clinic"
        phone = re.sub(r"[^\d+]", "", p.get("nationalPhoneNumber") or "")
        days = (p.get("regularOpeningHours") or {}).get("weekdayDescriptions") or []
        today = days[datetime.now(timezone(timedelta(hours=5, minutes=30))).weekday()] if len(days) == 7 else None  # Monday first, like Python
        address = _clean(re.sub(r",?\s*India\s*$", "", p.get("formattedAddress") or ""), 300)
        specs = (["jan aushadhi"] if _JAN_AUSHADHI.search(name) else []) if kind == "pharmacy" else _specialties({}, name)
        rating = p.get("rating")
        return Place(
            id=f"gmaps:{pid}", name=name, kind=kind, lat=float(loc["latitude"]), lon=float(loc["longitude"]), specialties=specs, address=address,
            phone=phone if 6 <= len(phone.lstrip("+")) <= 15 else None, website=_website({"website": p.get("websiteUri") or ""}), opening_hours=_clean(today, 120),
            emergency=kind == "hospital", rating=float(rating) if isinstance(rating, (int, float)) else None,
            rating_count=int(p["userRatingCount"]) if isinstance(p.get("userRatingCount"), int) else None, maps_url=_clean(p.get("googleMapsUri"), 300),
        )

    async def _google_nearby(self, lat: float, lon: float, radius_km: float, kind: str | None) -> list[Place]:
        body = {
            "includedTypes": self._G_TYPES[kind], "maxResultCount": 20, "rankPreference": "DISTANCE", "languageCode": "en", "regionCode": "IN",
            "locationRestriction": {"circle": {"center": {"latitude": float(lat), "longitude": float(lon)}, "radius": float(min(max(radius_km, 1), 50) * 1000)}},
        }
        try:
            resp = await self.http.post(f"{self.s.google_places_url}/places:searchNearby", json=body, headers=self._g_headers(self._G_FIELDS), timeout=self.s.places_timeout_seconds)
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not reach Google Maps.", retryable=True, code="places_unavailable") from exc
        if resp.status_code != 200:
            try:
                why = (resp.json().get("error") or {}).get("message", "")[:160]
            except ValueError:
                why = ""
            log.warning("Google Places failed: HTTP %s %s", resp.status_code, why)  # the key is never logged
            raise UpstreamError("Google Maps could not answer.", retryable=resp.status_code >= 500 or resp.status_code == 429, code="places_unavailable")
        try:
            rows = resp.json().get("places") or []
        except ValueError as exc:
            raise UpstreamError("Google Maps sent an unreadable answer.", retryable=True, code="places_unavailable") from exc
        wanted = {"hospital": ("hospital",), "clinic": ("clinic", "phc", "doctor"), "doctor": ("doctor",), "pharmacy": ("pharmacy",)}.get(kind or "")
        out: dict[str, Place] = {}
        for row in rows:
            place = self.parse_google(row)
            if place and (wanted is None or place.kind in wanted):
                out[place.id] = place
        return list(out.values())

    async def _google_get(self, place_id: str) -> Place | None:
        fields = ",".join(f.removeprefix("places.") for f in self._G_FIELDS.split(","))
        try:
            resp = await self.http.get(f"{self.s.google_places_url}/places/{place_id.removeprefix('gmaps:')}", headers=self._g_headers(fields), timeout=self.s.places_timeout_seconds)
            return self.parse_google(resp.json()) if resp.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    # ------------------------------------------------------------------ Overpass (optional, more complete)
    async def _overpass(self, query: str) -> list[dict[str, Any]]:
        last: Exception | None = None
        urls = [u for u in (self.s.overpass_url, self.s.overpass_fallback_url) if u]
        if not urls:
            raise UpstreamError("Overpass is not configured.", code="places_unavailable")
        for url in urls:
            try:
                resp = await self.http.post(url, data={"data": query}, headers=self._headers, timeout=self.s.places_timeout_seconds)
                if resp.status_code == 200:
                    return resp.json().get("elements", [])
                last = RuntimeError(f"HTTP {resp.status_code}")
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
            log.warning("Overpass %s failed: %s", url, last)
        raise UpstreamError("The map service is busy. Please try again in a moment.", retryable=True, code="places_unavailable") from last

    async def nearby(self, lat: float, lon: float, *, radius_km: float = 8, kind: str | None = None) -> list[Place]:
        """Every named hospital / clinic / doctor within radius_km, nearest first (cached for a few hours)."""
        self._require()
        radius_m = int(max(1, min(radius_km, 25)) * 1000)
        key = (round(lat, 2), round(lon, 2), radius_m, (kind or "") + ("|g" if self.s.google_places_active else ""))
        hit = self._near.get(key)
        if hit and self._fresh(hit[1]):
            places = hit[0]
        else:
            wanted = {"hospital": ("hospital",), "clinic": ("clinic", "phc"), "doctor": ("doctor",), "pharmacy": ("pharmacy",)}.get(kind or "")
            places = []
            if self.s.google_places_active:  # the better source; any failure quietly falls back to OpenStreetMap below
                try:
                    places = await self._google_nearby(lat, lon, radius_km, kind)
                except UpstreamError:
                    log.warning("Google Places failed; using OpenStreetMap for this search")
            if not places and self.s.overpass_url:  # optional: complete lists for big cities. Any failure falls back to Nominatim.
                try:
                    seen: dict[str, Place] = {}
                    for el in await self._overpass(_nearby_query(lat, lon, radius_m, kind)):
                        place = parse_element(el)
                        if place and (wanted is None or place.kind in wanted):  # the query already filters; this keeps the contract if a tag is odd
                            seen[place.id] = place
                    places = list(seen.values())
                except UpstreamError:
                    log.warning("Overpass failed; using Nominatim for the place list")
            if not places:
                places = await self._nominatim_nearby(lat, lon, radius_m / 1000, kind)
            self._near[key] = (places, time.time())
            if len(self._near) > 500:  # keep memory bounded
                self._near.pop(next(iter(self._near)))
        out = [replace(p, distance_km=round(haversine_km(lat, lon, p.lat, p.lon), 2)) for p in places]
        for p in out:
            self._by_id[p.id] = (p, time.time())
        out.sort(key=lambda p: (p.distance_km if p.distance_km is not None else 1e9, p.name))
        return out

    async def search(
        self, *, city: str | None = None, lat: float | None = None, lon: float | None = None, radius_km: float = 8,
        kind: str | None = None, q: str | None = None, specialty: str | None = None, limit: int = 30,
    ) -> SearchResult:
        label: str | None = None
        if lat is None or lon is None:
            if not city or not city.strip():
                raise NotFound("Tell me a city or share your location.", code="location_required", status_code=400)
            lat, lon, label = await self.geocode(city)
        places = await self.nearby(lat, lon, radius_km=radius_km, kind=kind)
        if q and q.strip():
            needle = q.strip().lower()
            places = [p for p in places if needle in p.name.lower() or any(needle in s for s in p.specialties)]
        if specialty:
            matched = [p for p in places if specialty in p.specialties]
            # Hospitals are kept as well: many have the department even when OpenStreetMap does not list it.
            others = [p for p in places if p not in matched and p.kind in ("hospital", "phc")]
            places = matched + others
        return SearchResult(center=(lat, lon, label), places=places[:limit], truncated=len(places) > limit)

    async def search_widening(self, *, radius_km: float, min_results: int = 3, steps: tuple[float, ...] = (15, 25), **kw) -> tuple[SearchResult, float]:
        """Search, and when there are too few places widen the circle (small towns have few shops on the map). Returns the result and the radius used."""
        radii = [radius_km] + [r for r in steps if r > radius_km]
        result = await self.search(radius_km=radii[0], **kw)
        used = radii[0]
        for r in radii[1:]:
            if len(result.places) >= min_results:
                break
            result, used = await self.search(radius_km=r, **kw), r
        return result, used

    async def get(self, place_id: str) -> Place:
        """One place by id (from the cache, else looked up on Overpass)."""
        self._require()
        if _GOOGLE_ID_RE.match(place_id or ""):
            hit = self._by_id.get(place_id)
            if hit and self._fresh(hit[1]):
                return hit[0]
            found = await self._google_get(place_id) if self.s.google_places_active else None
            if found is None:
                raise NotFound("I could not find that place any more.", code="place_not_found")
            self._by_id[found.id] = (found, time.time())
            return found
        m = _ID_RE.match(place_id or "")
        if not m:
            raise NotFound("That place id is not valid.", code="place_not_found")
        hit = self._by_id.get(place_id)
        if hit and self._fresh(hit[1]):
            return hit[0]
        place = None
        if self.s.overpass_url:
            try:
                elements = await self._overpass(f"[out:json][timeout:25];{m.group(1)}({m.group(2)});out center tags;")
                place = next((p for p in (parse_element(e) for e in elements) if p), None)
            except UpstreamError:
                place = None
        if place is None:  # Nominatim looks one object up by type letter + id, e.g. N123 / W456 / R789
            rows = await self._nominatim_get(self._lookup_url, {
                "osm_ids": m.group(1)[0].upper() + m.group(2), "format": "jsonv2", "addressdetails": 1, "extratags": 1, "namedetails": 1, "accept-language": "en",
            })
            place = next((p for p in (parse_nominatim(r) for r in rows) if p), None)
        if place is None:
            raise NotFound("I could not find that place any more.", code="place_not_found")
        self._by_id[place.id] = (place, time.time())
        return place
