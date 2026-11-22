"""Find real hospitals and clinics near a city or GPS position (OpenStreetMap), plus any registered partner clinics."""
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import User
from app.database.repositories.providers import ProviderRepository
from app.schemas.family import PlaceOut, PlacesOut, SearchCenter
from app.services.places import ATTRIBUTION, GOOGLE_ATTRIBUTION, Place, PlacesService

router = APIRouter(prefix="/places", tags=["places"])

NOTE = (
    "A phone number or opening hours may be missing or out of date. "
    "They have no online booking, so a visit is only planned and you should phone to confirm it."
)
NOTE_GOOGLE = (
    "These places come from Google Maps: a phone number or opening hours may be missing or out of date. "
    "They have no online booking, so a visit is only planned and you should phone to confirm it."
)


PHARMACY_NOTE = (
    "A phone number or opening hours may be missing or out of date. "
    "Phone ahead if you need a medicine urgently. A prescription is needed for many medicines."
)
PHARMACY_NOTE_GOOGLE = (
    "Shops come from Google Maps: a phone number or opening hours may be missing or out of date. "
    "Phone ahead if you need a medicine urgently. A prescription is needed for many medicines."
)


def place_out(p: Place) -> PlaceOut:
    return PlaceOut(
        id=p.id, name=p.name, kind=p.kind, specialties=p.specialties, address=p.address, city=p.city, phone=p.phone,  # type: ignore[arg-type]
        website=p.website, opening_hours=p.opening_hours, lat=p.lat, lon=p.lon, distance_km=p.distance_km, emergency=p.emergency,
        rating=p.rating, rating_count=p.rating_count, maps_url=p.maps_url, source="google" if p.is_google else "openstreetmap", has_slots=False, provider_code=None,
    )


@router.get("/search", response_model=PlacesOut)
async def search_places(
    request: Request,
    city: str | None = Query(default=None, max_length=80, description="City or town, e.g. 'Guntur'. Send this OR lat+lon"),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
    radius_km: float = Query(default=8, ge=1, le=25),
    kind: Literal["hospital", "clinic", "doctor", "pharmacy"] | None = None,
    q: str | None = Query(default=None, max_length=60, description="Filter by name or specialty"),
    specialty: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=30, ge=1, le=60),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> PlacesOut:
    if (lat is None) != (lon is None):
        raise BadRequest("Send both lat and lon, or a city.", code="location_required")
    places: PlacesService = request.app.state.places
    spec = specialty.lower() if specialty else None
    if kind == "pharmacy":  # a small town may have no shop on the map within a few km: widen the circle instead of showing nothing
        result, used_km = await places.search_widening(city=city, lat=lat, lon=lon, radius_km=radius_km, kind=kind, q=q, specialty=spec, limit=limit)
    else:
        result, used_km = await places.search(city=city, lat=lat, lon=lon, radius_km=radius_km, kind=kind, q=q, specialty=spec, limit=limit), radius_km
    items = [place_out(p) for p in result.places]

    # Partner clinics (registered with their own schedule) in the same city come first: they can confirm a real slot.
    partners = []
    if city and city.strip() and kind != "pharmacy":
        for p in await ProviderRepository(session).search(city=city, specialty=specialty.lower() if specialty else None, limit=10):
            partners.append(PlaceOut(
                id=p.code, name=p.name, kind=p.kind if p.kind in ("hospital", "clinic", "phc") else "clinic", specialties=p.specialties or [],  # type: ignore[arg-type]
                address=p.address, city=p.city, phone=p.phone, website=p.website, opening_hours=p.opening_hours, lat=p.lat, lon=p.lon,
                emergency=p.kind == "hospital", source="partner", has_slots=True, provider_code=p.code,
            ))
    google = any(p.is_google for p in result.places)
    lat0, lon0, label = result.center
    return PlacesOut(
        center=SearchCenter(lat=lat0, lon=lon0, label=label), items=partners + items, attribution=GOOGLE_ATTRIBUTION if any(p.is_google for p in result.places) else ATTRIBUTION,
        note=((f"Nothing was listed within {radius_km:g} km, so this shows shops within {used_km:g} km. " if used_km > radius_km and items else "") + (PHARMACY_NOTE_GOOGLE if google else PHARMACY_NOTE) if kind == "pharmacy" else (NOTE_GOOGLE if google else NOTE)) if items else ("Nothing found in this radius. Try a larger radius or the nearest big town." if not partners else None),
    )
