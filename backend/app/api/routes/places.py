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
from app.services.places import ATTRIBUTION, Place, PlacesService

router = APIRouter(prefix="/places", tags=["places"])

NOTE = (
    "These places come from OpenStreetMap, which volunteers edit: a phone number or opening hours may be missing or out of date. "
    "They have no online booking, so a visit is only planned and you should phone to confirm it."
)


def place_out(p: Place) -> PlaceOut:
    return PlaceOut(
        id=p.id, name=p.name, kind=p.kind, specialties=p.specialties, address=p.address, city=p.city, phone=p.phone,  # type: ignore[arg-type]
        website=p.website, opening_hours=p.opening_hours, lat=p.lat, lon=p.lon, distance_km=p.distance_km, emergency=p.emergency,
        source="openstreetmap", has_slots=False, provider_code=None,
    )


@router.get("/search", response_model=PlacesOut)
async def search_places(
    request: Request,
    city: str | None = Query(default=None, max_length=80, description="City or town, e.g. 'Guntur'. Send this OR lat+lon"),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
    radius_km: float = Query(default=8, ge=1, le=25),
    kind: Literal["hospital", "clinic", "doctor"] | None = None,
    q: str | None = Query(default=None, max_length=60, description="Filter by name or specialty"),
    specialty: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=30, ge=1, le=60),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> PlacesOut:
    if (lat is None) != (lon is None):
        raise BadRequest("Send both lat and lon, or a city.", code="location_required")
    places: PlacesService = request.app.state.places
    result = await places.search(city=city, lat=lat, lon=lon, radius_km=radius_km, kind=kind, q=q, specialty=specialty.lower() if specialty else None, limit=limit)
    items = [place_out(p) for p in result.places]

    # Partner clinics (registered with their own schedule) in the same city come first: they can confirm a real slot.
    partners = []
    if city and city.strip():
        for p in await ProviderRepository(session).search(city=city, specialty=specialty.lower() if specialty else None, limit=10):
            partners.append(PlaceOut(
                id=p.code, name=p.name, kind=p.kind if p.kind in ("hospital", "clinic", "phc") else "clinic", specialties=p.specialties or [],  # type: ignore[arg-type]
                address=p.address, city=p.city, phone=p.phone, website=p.website, opening_hours=p.opening_hours, lat=p.lat, lon=p.lon,
                emergency=p.kind == "hospital", source="partner", has_slots=True, provider_code=p.code,
            ))
    lat0, lon0, label = result.center
    return PlacesOut(
        center=SearchCenter(lat=lat0, lon=lon0, label=label), items=partners + items, attribution=ATTRIBUTION,
        note=NOTE if items else ("Nothing found in this radius. Try a larger radius or the nearest big town." if not partners else None),
    )
