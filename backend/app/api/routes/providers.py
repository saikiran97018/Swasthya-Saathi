from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings
from app.api.mappers import provider_out
from app.core.config import Settings
from app.core.errors import BadRequest, NotFound
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import User
from app.database.repositories.providers import ProviderRepository
from app.schemas.misc import ProviderOut, SlotsOut
from app.services.appointments import AppointmentService
from app.services.scheduling import SPECIALTIES

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("", response_model=list[ProviderOut])
async def search_providers(
    request: Request,
    specialty: str | None = Query(default=None, description="One of: " + ", ".join(SPECIALTIES)),
    city: str | None = Query(default=None, max_length=80),
    language: str | None = Query(default=None, max_length=8),
    teleconsultation: bool | None = None,
    accepts_ayushman: bool | None = None,
    limit: int = Query(default=12, ge=1, le=50),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
    settings: Settings = Depends(get_app_settings),
) -> list[ProviderOut]:
    """Discover healthcare providers. Listings flagged `is_demo` are sample data."""
    if specialty and specialty.lower() not in SPECIALTIES:
        raise BadRequest(f"Unknown specialty. Use one of: {', '.join(SPECIALTIES)}", code="invalid_specialty")
    svc = AppointmentService(session, settings, request.app.state.http)
    rows = await ProviderRepository(session).search(
        specialty=specialty, city=city, language=language, teleconsultation=teleconsultation, accepts_ayushman=accepts_ayushman, limit=limit
    )
    ratings = await ProviderRepository(session).ratings([p.id for p in rows])
    out = []
    for p in rows:
        slots = await svc.open_slots(p, days=7)
        first = next(iter(slots.items()), None)
        out.append(provider_out(p, {"date": first[0], "time": first[1][0]} if first else None, ratings.get(p.id)))
    return out


@router.get("/{code}/availability", response_model=SlotsOut)
async def availability(
    request: Request, code: str,
    from_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    days: int = Query(default=5, ge=1, le=14),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
    settings: Settings = Depends(get_app_settings),
) -> SlotsOut:
    provider = await ProviderRepository(session).get_by_code(code)
    if provider is None:
        raise NotFound("Provider not found", code="provider_not_found")
    try:
        start = datetime.strptime(from_date, "%Y-%m-%d").date() if from_date else None
    except ValueError as exc:
        raise BadRequest("from_date must be YYYY-MM-DD", code="invalid_date") from exc
    slots = await AppointmentService(session, settings, request.app.state.http).open_slots(provider, from_date=start, days=days)
    rating = (await ProviderRepository(session).ratings([provider.id])).get(provider.id)
    return SlotsOut(provider=provider_out(provider, None, rating), slot_minutes=provider.slot_minutes, open_slots=slots)
