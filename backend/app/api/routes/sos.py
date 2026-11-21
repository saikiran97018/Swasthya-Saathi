"""SOS screen data and the user's emergency contacts.

Nothing here calls, texts or alerts anyone: the app only shows numbers and tap-to-call links. Sharing a location is done
by the user's own phone (an SMS link prepared in the browser), never by this server.
"""
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, BadRequest, Conflict, NotFound
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import User
from app.database.repositories.family import MAX_EMERGENCY_CONTACTS, EmergencyContactRepository, emergency_capable_providers
from app.schemas.family import EmergencyContactIn, EmergencyContactOut, SosFacility, SosOut
from app.services import sos_content
from app.services.appointments import normalise_mobile

router = APIRouter(tags=["sos"])


@router.get("/sos", response_model=SosOut)
async def sos(
    request: Request,
    city: str | None = Query(default=None, max_length=80, description="Optional city, e.g. 'Guntur', to list hospitals near it"),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> SosOut:
    """Helplines and first aid always come back. Nearby hospitals are best effort: if the map service is down the list is
    simply empty (this screen must never fail when someone needs it)."""
    nearby: list[SosFacility] = []
    if (lat is not None and lon is not None) or (city and city.strip()):
        try:
            found = await request.app.state.places.search(city=city, lat=lat, lon=lon, radius_km=15, kind="hospital", limit=6)
            nearby = [
                SosFacility(code=p.id, name=p.name, kind=p.kind, city=p.city, address=p.address, phone=p.phone, lat=p.lat, lon=p.lon, distance_km=p.distance_km, source="openstreetmap")
                for p in found.places
            ]
        except AppError:
            nearby = []
    if city and city.strip():  # clinics that registered with us go first
        partners = [
            SosFacility(code=p.code, name=p.name, kind=p.kind, city=p.city, address=p.address, phone=p.phone, teleconsultation=p.teleconsultation, is_demo=p.is_demo, lat=p.lat, lon=p.lon, source="partner")
            for p in await emergency_capable_providers(session, city)
        ]
        nearby = partners + nearby
    return SosOut(numbers=sos_content.NUMBERS, nearby=nearby, first_aid=sos_content.FIRST_AID, disclaimer=sos_content.DISCLAIMER)


@router.get("/emergency-contacts", response_model=list[EmergencyContactOut])
async def list_contacts(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> list[EmergencyContactOut]:
    return [EmergencyContactOut.model_validate(c) for c in await EmergencyContactRepository(session).list(user.id)]


@router.post("/emergency-contacts", response_model=EmergencyContactOut, status_code=201)
async def add_contact(body: EmergencyContactIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> EmergencyContactOut:
    repo = EmergencyContactRepository(session)
    phone = normalise_mobile(body.phone)
    if phone is None:
        raise BadRequest("The phone number must be a 10-digit Indian mobile number starting with 6, 7, 8 or 9.", code="invalid_mobile")
    if await repo.count(user.id) >= MAX_EMERGENCY_CONTACTS:
        raise Conflict(f"You can save up to {MAX_EMERGENCY_CONTACTS} emergency contacts. Remove one first.", code="contact_limit")
    relation = (body.relation or "").strip() or None
    return EmergencyContactOut.model_validate(await repo.add(user_id=user.id, name=body.name, phone=phone, relation=relation))


@router.delete("/emergency-contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> Response:
    repo = EmergencyContactRepository(session)
    contact = await repo.get_owned(user.id, contact_id)
    if contact is None:
        raise NotFound("Emergency contact not found", code="contact_not_found")
    await repo.delete(contact)
    return Response(status_code=204)
