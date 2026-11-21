import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings
from app.api.mappers import appointment_out, booking_to_http
from app.core.config import Settings
from app.core.errors import BadRequest, Forbidden, NotFound
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import User
from app.database.repositories.family import FamilyRepository
from app.database.repositories.providers import ProviderRepository
from app.database.repositories.users import UserRepository
from app.schemas.misc import AppointmentOut, AppointmentPage, BookIn, CancelIn, FeedbackIn
from app.services import scheduling as sched
from app.services.appointments import AppointmentService, BookingError
from app.utils.language import normalise_language

router = APIRouter(prefix="/appointments", tags=["appointments"])


def _svc(request: Request, session: AsyncSession, settings: Settings) -> AppointmentService:
    return AppointmentService(session, settings, request.app.state.http)


async def _owned(svc: AppointmentService, user: User, appointment_id: uuid.UUID):
    appt = await svc.appts.get_owned(user.id, appointment_id)
    if appt is None:
        raise NotFound("Appointment not found", code="appointment_not_found")
    return appt


async def _out(svc: AppointmentService, appt) -> AppointmentOut:
    return appointment_out(appt, await svc.reminders.for_appointment(appt.id))


@router.post("", response_model=AppointmentOut, status_code=201)
async def book_appointment(
    request: Request,
    body: BookIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
    settings: Settings = Depends(get_app_settings),
) -> AppointmentOut:
    """Book from the UI. The patient pressed an explicit "Confirm" button after reviewing the details, which is the
    consent step. All rules (valid slot, lead time, limits, no double-booking) are the same ones the agent's tool uses.

    `provider_code` books a partner clinic's real slot. `place_id` saves a PLANNED visit at a real place (OpenStreetMap):
    the response has `clinic_confirmed: false` because the clinic has not agreed to that time."""
    svc = _svc(request, session, settings)
    providers = ProviderRepository(session)
    if body.place_id:  # a real place found via /places/search: it gets a provider row the first time someone plans a visit there
        place = await request.app.state.places.get(body.place_id)
        provider = await providers.get_or_create_from_place(place)
    else:
        provider = await providers.get_by_code(body.provider_code or "")
        if provider is None:
            raise NotFound("Provider not found", code="provider_not_found")
    try:
        starts_at = sched.parse_local_slot(body.slot_start)
    except ValueError as exc:
        raise BadRequest(str(exc), code="invalid_slot") from exc
    language = normalise_language(body.language, await UserRepository(session).primary_language(user.id))
    if body.family_member_id is not None and await FamilyRepository(session).get_owned(user.id, body.family_member_id) is None:
        raise NotFound("Family member not found", code="family_member_not_found")
    try:
        appt = await svc.book(
            user=user, conversation_id=None, provider=provider, starts_at=starts_at, patient_name=body.patient_name,
            patient_mobile=body.patient_mobile, reason=body.reason, mode=body.mode, language=language, family_member_id=body.family_member_id,
        )
    except BookingError as exc:
        raise booking_to_http(exc) from exc
    return await _out(svc, appt)


@router.post("/{appointment_id}/feedback", response_model=AppointmentOut)
async def give_feedback(
    request: Request, appointment_id: uuid.UUID, body: FeedbackIn, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"), settings: Settings = Depends(get_app_settings),
) -> AppointmentOut:
    """Star rating (and optional comment) after the visit, from the Care Plan screen."""
    svc = _svc(request, session, settings)
    appt = await _owned(svc, user, appointment_id)
    try:
        await svc.record_feedback(appt, body.rating, body.comment)
    except BookingError as exc:
        raise booking_to_http(exc) from exc
    return await _out(svc, appt)


@router.get("", response_model=AppointmentPage)
async def list_appointments(
    request: Request,
    scope: str = Query(default="upcoming", pattern="^(upcoming|past|all)$"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
    settings: Settings = Depends(get_app_settings),
) -> AppointmentPage:
    svc = _svc(request, session, settings)
    rows, total = await svc.appts.list_for_user(user.id, scope=scope, limit=limit, offset=offset)
    return AppointmentPage(items=[await _out(svc, a) for a in rows], total=total, limit=limit, offset=offset)


@router.get("/{appointment_id}", response_model=AppointmentOut)
async def get_appointment(
    request: Request, appointment_id: uuid.UUID, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"), settings: Settings = Depends(get_app_settings),
) -> AppointmentOut:
    svc = _svc(request, session, settings)
    return await _out(svc, await _owned(svc, user, appointment_id))


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel_appointment(
    request: Request, appointment_id: uuid.UUID, body: CancelIn | None = None, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"), settings: Settings = Depends(get_app_settings),
) -> AppointmentOut:
    """User-initiated cancel from the UI (the person pressed the button, so no extra confirmation step)."""
    svc = _svc(request, session, settings)
    appt = await _owned(svc, user, appointment_id)
    try:
        await svc.cancel(appt, body.reason if body else None)
    except BookingError as exc:
        raise booking_to_http(exc) from exc
    return await _out(svc, appt)


@router.post("/{appointment_id}/complete", response_model=AppointmentOut)
async def demo_complete(
    request: Request, appointment_id: uuid.UUID, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"), settings: Settings = Depends(get_app_settings),
) -> AppointmentOut:
    """DEMO helper: pretend the visit took place so feedback can be tried. Disabled when DEMO_MODE=false."""
    if not settings.demo_mode:
        raise Forbidden("Demo helpers are disabled", code="demo_disabled")
    svc = _svc(request, session, settings)
    appt = await _owned(svc, user, appointment_id)
    try:
        await svc.demo_complete(appt)
    except BookingError as exc:
        raise booking_to_http(exc) from exc
    await session.commit()
    await request.app.state.reminder_service.deliver_due()  # the feedback request is now due
    await session.refresh(appt)
    return await _out(svc, appt)


@router.post("/{appointment_id}/remind-now", response_model=AppointmentOut)
async def demo_remind_now(
    request: Request, appointment_id: uuid.UUID, user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"), settings: Settings = Depends(get_app_settings),
) -> AppointmentOut:
    """DEMO helper: deliver a reminder for this appointment right now. Disabled when DEMO_MODE=false."""
    if not settings.demo_mode:
        raise Forbidden("Demo helpers are disabled", code="demo_disabled")
    svc = _svc(request, session, settings)
    appt = await _owned(svc, user, appointment_id)
    if appt.status != "booked":
        raise booking_to_http(BookingError(f"Appointment {appt.ref} is {appt.status}.", "not_active"))
    await svc.demo_remind_now(appt)
    await session.commit()
    await request.app.state.reminder_service.deliver_due()
    return await _out(svc, appt)
