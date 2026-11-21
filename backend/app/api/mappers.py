"""Model -> schema conversions for providers, appointments and notifications."""
from __future__ import annotations

from app.core.errors import BadRequest
from app.database.models import Appointment, Provider, Reminder
from app.schemas.family import FamilyMemberRef
from app.schemas.misc import AppointmentOut, NotificationOut, ProviderOut, ReminderInfo
from app.services.appointments import BookingError


def mask_mobile(m: str) -> str:
    return f"{m[:2]}XXXXXX{m[-2:]}" if len(m) >= 6 else "XXXX"


def provider_out(p: Provider, next_available: dict[str, str] | None = None, rating: tuple[float | None, int] | None = None) -> ProviderOut:
    return ProviderOut(
        code=p.code, name=p.name, kind=p.kind, doctor_name=p.doctor_name, specialties=p.specialties or [], city=p.city, state=p.state,
        address=p.address, phone=p.phone, languages=p.languages or [], fee_inr=p.fee_inr, accepts_ayushman=p.accepts_ayushman,
        teleconsultation=p.teleconsultation, is_demo=p.is_demo, next_available=next_available,
        rating_avg=round(rating[0], 2) if rating and rating[0] is not None else None, rating_count=rating[1] if rating else 0,
        source=p.source or "partner", lat=p.lat, lon=p.lon, website=p.website, opening_hours=p.opening_hours,  # type: ignore[arg-type]
    )


def appointment_out(a: Appointment, reminders: list[Reminder] | None = None) -> AppointmentOut:
    return AppointmentOut(
        id=a.id, ref=a.ref, status=a.status, mode=a.mode, starts_at=a.starts_at, ends_at=a.ends_at,  # type: ignore[arg-type]
        patient_name=a.patient_name, patient_mobile=mask_mobile(a.patient_mobile), reason=a.reason, language=a.language,
        provider=provider_out(a.provider), reschedule_count=a.reschedule_count, feedback_rating=a.feedback_rating,
        feedback_comment=a.feedback_comment, conversation_id=a.conversation_id, created_at=a.created_at,
        clinic_confirmed=a.clinic_confirmed, family_member=FamilyMemberRef.model_validate(a.family_member) if a.family_member else None,
        reminders=[ReminderInfo(kind=r.kind, due_at=r.due_at, status=r.status) for r in (reminders or [])],
    )


def notification_out(r: Reminder) -> NotificationOut:
    return NotificationOut(
        id=r.id, kind=r.kind, title=r.title, message=r.delivered_message or r.message, language=r.language,  # type: ignore[arg-type]
        appointment_ref=(r.payload or {}).get("appointment_ref"), conversation_id=r.conversation_id,
        delivered_at=r.delivered_at, read_at=r.read_at,  # type: ignore[arg-type]
    )


def booking_to_http(exc: BookingError) -> BadRequest:
    return BadRequest(exc.message, code=exc.code)
