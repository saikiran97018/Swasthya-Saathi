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
_ID_RE = re.compile(r"^osm:(node|way|relation)/(\d{1,14})$")
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
    kind: str  # hospital | clinic | doctor | phc | other
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

    @property
    def osm_key(self) -> str:
        return self.id.removeprefix("osm:")

    @property
    def provider_code(self) -> str:
        """Short speakable code that fits Provider.code, e.g. OSM-N123456 (N = node, W = way, R = relation)."""
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


_AMENITY = {"hospital": "hospital", "clinic": "clinic", "doctor": "doctors", None: "hospital|clinic|doctors"}
_HEALTHCARE = {"hospital": "hospital", "clinic": "clinic|centre", "doctor": "doctor", None: "hospital|clinic|doctor|centre"}


def _nearby_query(lat: float, lon: float, radius_m: int, kind: str | None) -> str:
    """Overpass QL: named-or-not hospitals / clinics / doctors around a point (nodes, ways and relations)."""
    around = f"(around:{radius_m},{float(lat)},{float(lon)})"  # floats only: nothing user-typed ever reaches the query text
    return (
        "[out:json][timeout:25];("
        f'nwr["amenity"~"^({_AMENITY[kind]})$"]{around};'
        f'nwr["healthcare"~"^({_HEALTHCARE[kind]})$"]{around};'
        ");out center tags 300;"
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
    return Place(
        id=f"osm:{kind_type}/{el['id']}", name=name, kind=kind, lat=float(lat), lon=float(lon), specialties=_specialties(tags, name),
        address=address, city=city, phone=_phone(tags), website=_website(tags), opening_hours=_clean(tags.get("opening_hours")),
        emergency=tags.get("emergency") == "yes" or kind == "hospital",
    )


_NOMINATIM_TERMS = {"hospital": ["hospital"], "clinic": ["clinic"], "doctor": ["doctors"], None: ["hospital", "clinic", "doctors"]}
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
        wanted = {"hospital": ("hospital",), "clinic": ("clinic", "phc"), "doctor": ("doctor",)}.get(kind or "")
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
        key = (round(lat, 2), round(lon, 2), radius_m, kind or "")
        hit = self._near.get(key)
        if hit and self._fresh(hit[1]):
            places = hit[0]
        else:
            wanted = {"hospital": ("hospital",), "clinic": ("clinic", "phc"), "doctor": ("doctor",)}.get(kind or "")
            places = []
            if self.s.overpass_url:  # optional: complete lists for big cities. Any failure falls back to Nominatim.
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

    async def get(self, place_id: str) -> Place:
        """One place by id (from the cache, else looked up on Overpass)."""
        self._require()
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
