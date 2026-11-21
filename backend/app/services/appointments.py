"""Appointment business logic shared by the agent tools and the REST API.

All rules live here (slot validity, double-booking, limits, reminders), so the language model can
never bypass them and the UI and the agent behave identically.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.database.models import Appointment, FamilyMember, Provider, Reminder, User, utcnow
from app.database.repositories.appointments import AppointmentRepository, ReminderRepository
from app.database.repositories.providers import ProviderRepository
from app.services import scheduling as sched
from app.services.webhooks import send_webhook

_MOBILE = re.compile(r"^[6-9]\d{9}$")


class BookingError(Exception):
    """A business-rule failure with a message that is safe to show the user / model."""

    def __init__(self, message: str, code: str = "booking_error"):
        super().__init__(message)
        self.message, self.code = message, code


def normalise_mobile(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits if _MOBILE.match(digits) else None


def appointment_dict(a: Appointment) -> dict[str, Any]:
    p = a.provider
    when = sched.describe(a.starts_at)
    return {
        "reference": a.ref, "status": a.status, "mode": a.mode,
        "provider": {"code": p.code, "name": p.name, "doctor": p.doctor_name, "city": p.city, "address": p.address, "phone": p.phone, "is_demo_listing": p.is_demo},
        "date": when["date"], "day": when["day"], "time": when["time"], "when": when["display"],
        "patient_name": a.patient_name, "reason": a.reason, "feedback_rating": a.feedback_rating,
        "clinic_confirmed": a.clinic_confirmed,
        **({} if a.clinic_confirmed else {"important": "NOT confirmed by the clinic: tell the user to phone the clinic to confirm this time."}),
    }


class AppointmentService:
    def __init__(self, session: AsyncSession, settings: Settings, http: httpx.AsyncClient | None = None):
        self.session, self.s, self.http = session, settings, http
        self.appts = AppointmentRepository(session)
        self.reminders = ReminderRepository(session)
        self.providers = ProviderRepository(session)

    # ------------------------------------------------------------------ availability
    async def open_slots(self, provider: Provider, *, from_date: date | None = None, days: int = 5, now: datetime | None = None) -> dict[str, list[str]]:
        """Open slots per local date: {'2026-11-22': ['10:00', '10:20', ...]}."""
        now = now or utcnow()
        earliest, latest = sched.bookable_window(now, self.s.booking_horizon_days)
        first = from_date or sched.to_ist(earliest).date()
        booked = await self.appts.booked_starts(provider.id, earliest, latest + timedelta(days=1))
        result: dict[str, list[str]] = {}
        for offset in range(max(1, min(days, self.s.booking_horizon_days))):
            day = first + timedelta(days=offset)
            # aware datetimes compare/hash by instant, so IST slots match the UTC values from the database
            slots = [s for s in sched.slots_on(provider.schedule, provider.slot_minutes, day) if earliest <= s <= latest and s not in booked]
            if slots:
                result[day.isoformat()] = [s.strftime("%H:%M") for s in slots]
        return result

    def earliest_visit_time(self, now: datetime | None = None) -> datetime:
        """The soonest time a visit can be planned: now plus the lead time, rounded UP to the next 10 minutes (IST)."""
        # +1 minute of margin: the user takes a moment to answer, and a time that is only just valid must still be valid then
        t = sched.to_ist((now or utcnow()) + timedelta(minutes=self.s.planned_visit_min_lead_minutes + 1))
        t = t.replace(second=0, microsecond=0) + (timedelta(minutes=1) if (t.second or t.microsecond) else timedelta())
        return t + timedelta(minutes=(-t.minute) % 10)

    def _lead_text(self) -> str:
        m = self.s.planned_visit_min_lead_minutes
        return f"{m // 60} hours" if m % 60 == 0 and m >= 120 else "1 hour" if m == 60 else f"{m} minutes"

    def _validate_visit_time(self, start: datetime, now: datetime) -> None:
        """A PLANNED visit at a real place has no slot grid: any time that is not too soon and not too far away."""
        if start < now + timedelta(minutes=self.s.planned_visit_min_lead_minutes):
            earliest = sched.describe(self.earliest_visit_time(now))["display"]
            raise BookingError(
                f"The earliest time you can plan right now is {earliest}: a visit must be at least {self._lead_text()} from now, so you have time to phone the clinic and confirm it.",
                "slot_in_past",
            )
        if start > now + timedelta(days=self.s.planned_visit_horizon_days):
            raise BookingError(f"A visit can only be planned up to {self.s.planned_visit_horizon_days} days ahead.", "slot_too_far")

    def _validate_slot(self, provider: Provider, start: datetime, now: datetime) -> None:
        earliest, latest = sched.bookable_window(now, self.s.booking_horizon_days)
        if not sched.is_on_grid(provider.schedule, provider.slot_minutes, start):
            raise BookingError(f"{sched.describe(start)['display']} is not one of {provider.name}'s appointment slots. Use check_availability to see valid times.", "invalid_slot")
        if start < earliest:
            raise BookingError("That time is too soon or already past. Choose a slot at least 30 minutes from now.", "slot_in_past")
        if start > latest:
            raise BookingError(f"Appointments can only be booked up to {self.s.booking_horizon_days} days ahead.", "slot_too_far")

    # ------------------------------------------------------------------ booking
    async def book(
        self, *, user: User, conversation_id: uuid.UUID | None, provider: Provider, starts_at: datetime,
        patient_name: str, patient_mobile: str, reason: str, mode: str = "in_person", language: str = "en", now: datetime | None = None,
        family_member_id: uuid.UUID | None = None,
    ) -> Appointment:
        now = now or utcnow()
        mobile = normalise_mobile(patient_mobile)
        if mobile is None:
            raise BookingError("The mobile number must be a 10-digit Indian number starting with 6, 7, 8 or 9.", "invalid_mobile")
        planned = provider.source == "osm"  # a real place with no online booking: the visit is only PLANNED, never confirmed by us
        if mode == "teleconsultation" and (planned or not provider.teleconsultation):
            raise BookingError(f"{provider.name} does not offer teleconsultation.", "no_teleconsultation")
        starts_at = starts_at.astimezone(sched.IST)
        if planned:
            self._validate_visit_time(starts_at, now)
        else:
            self._validate_slot(provider, starts_at, now)
        ends_at = starts_at + timedelta(minutes=provider.slot_minutes)

        if await self.appts.count_active(user.id, now) >= self.s.max_active_appointments:
            raise BookingError(f"You already have {self.s.max_active_appointments} upcoming appointments. Cancel one before booking another.", "too_many_appointments")
        clash = await self.appts.user_conflict(user.id, starts_at, ends_at, family_member_id=family_member_id)
        if clash:
            raise BookingError(f"{patient_name.strip()} already has appointment {clash.ref} at that time with {clash.provider.name}.", "user_conflict")

        appt = Appointment(
            user_id=user.id, conversation_id=conversation_id, provider_id=provider.id, ref=await self.appts.new_ref(),
            starts_at=starts_at, ends_at=ends_at, status="booked", mode=mode,
            patient_name=patient_name.strip(), patient_mobile=mobile, reason=reason.strip(), language=language,
            family_member_id=family_member_id, clinic_confirmed=not planned,
        )
        try:
            # The unique partial index rejects a slot taken a moment ago. The row is added INSIDE the savepoint so a
            # rollback also discards it (otherwise the stale pending row would break the surrounding transaction).
            async with self.session.begin_nested():
                self.session.add(appt)
                await self.session.flush()
        except IntegrityError as exc:
            raise BookingError("That slot was just taken by someone else. Please pick another time.", "slot_taken") from exc
        appt.provider = provider
        appt.family_member = await self.session.get(FamilyMember, family_member_id) if family_member_id else None  # loaded now: the response needs it
        await self._schedule_reminders(appt, now)
        await send_webhook(self.http, self.s, "appointment.booked", appointment_dict(appt))
        return appt

    async def _schedule_reminders(self, appt: Appointment, now: datetime) -> list[Reminder]:
        p, when = appt.provider, sched.describe(appt.starts_at)
        where = "Keep your phone ready: the doctor will call you." if appt.mode == "teleconsultation" else (f"Address: {p.address}." if p.address else f"Location: {p.name}, {p.city}.")
        call = f" Please call {p.phone} to confirm the time." if p.phone else " Please phone the clinic to confirm the time."
        if appt.clinic_confirmed:
            day_msg = f"Reminder: appointment {appt.ref} with {p.name} on {when['display']} for {appt.patient_name}. Please carry an ID and any previous reports."
            soon_msg = f"Your appointment {appt.ref} with {p.name} is in about 2 hours, at {when['time']}. {where}"
        else:  # a visit the user planned: the clinic never confirmed it, so every reminder says so
            day_msg = f"Reminder: your planned visit {appt.ref} to {p.name} on {when['display']} for {appt.patient_name}. The clinic has not confirmed this time.{call}"
            soon_msg = f"Your planned visit {appt.ref} to {p.name} is in about 2 hours, at {when['time']}. {where}{call}"
        plans = [
            ("appointment_reminder", appt.starts_at - timedelta(hours=24), "Appointment tomorrow" if appt.clinic_confirmed else "Planned visit tomorrow", day_msg),
            ("appointment_reminder", appt.starts_at - timedelta(hours=2), "Appointment in 2 hours" if appt.clinic_confirmed else "Planned visit in 2 hours", soon_msg),
            ("feedback_request", appt.ends_at + timedelta(hours=2), "How was your visit?",
             f"How was your visit with {p.name} ({appt.ref})? Tell me about it and give a rating from 1 to 5 - it helps improve care."),
        ]
        created = []
        for kind, due, title, message in plans:
            if due <= now and kind == "appointment_reminder":
                continue  # too late to remind
            created.append(await self.reminders.add(
                user_id=appt.user_id, conversation_id=appt.conversation_id, appointment_id=appt.id, kind=kind, due_at=due,
                title=title, message=message, language=appt.language, payload={"appointment_ref": appt.ref},
            ))
        return created

    async def reminder_times(self, appt: Appointment) -> list[dict[str, str]]:
        return [
            {"kind": r.kind, "when": sched.describe(r.due_at)["display"]}
            for r in await self.reminders.for_appointment(appt.id) if r.status == "pending"
        ]

    # ------------------------------------------------------------------ cancel / reschedule
    def _require_active(self, appt: Appointment, now: datetime) -> None:
        if appt.status != "booked":
            raise BookingError(f"Appointment {appt.ref} is already {appt.status}.", "not_active")
        if appt.starts_at <= now:
            raise BookingError(f"Appointment {appt.ref} has already started or passed.", "already_started")

    async def cancel(self, appt: Appointment, reason: str | None = None, now: datetime | None = None) -> Appointment:
        now = now or utcnow()
        self._require_active(appt, now)
        appt.status, appt.cancel_reason = "cancelled", (reason or "").strip() or None
        for r in await self.reminders.pending_for_appointment(appt.id):
            r.status = "cancelled"
        await self.session.flush()
        await send_webhook(self.http, self.s, "appointment.cancelled", appointment_dict(appt))
        return appt

    async def reschedule(self, appt: Appointment, new_start: datetime, now: datetime | None = None) -> Appointment:
        now = now or utcnow()
        self._require_active(appt, now)
        new_start = new_start.astimezone(sched.IST)
        if appt.clinic_confirmed:
            self._validate_slot(appt.provider, new_start, now)
        else:
            self._validate_visit_time(new_start, now)
        new_end = new_start + timedelta(minutes=appt.provider.slot_minutes)
        if await self.appts.user_conflict(appt.user_id, new_start, new_end, exclude_id=appt.id, family_member_id=appt.family_member_id):
            raise BookingError("You already have another appointment at that time.", "user_conflict")
        old = (appt.starts_at, appt.ends_at, appt.reschedule_count)
        try:
            # begin_nested() flushes pending changes on entry, so the change must be made INSIDE the savepoint,
            # otherwise a clash would fail outside it and poison the whole transaction.
            async with self.session.begin_nested():
                appt.starts_at, appt.ends_at, appt.reschedule_count = new_start, new_end, appt.reschedule_count + 1
                await self.session.flush()
        except IntegrityError as exc:
            appt.starts_at, appt.ends_at, appt.reschedule_count = old  # undo the in-memory change; the DB kept the old values
            raise BookingError("That slot was just taken by someone else. Please pick another time.", "slot_taken") from exc
        for r in await self.reminders.pending_for_appointment(appt.id):
            r.status = "cancelled"
        await self._schedule_reminders(appt, now)
        await send_webhook(self.http, self.s, "appointment.rescheduled", appointment_dict(appt))
        return appt

    # ------------------------------------------------------------------ follow-up & feedback
    async def schedule_follow_up(self, appt: Appointment, due_date: date, note: str | None, now: datetime | None = None) -> Reminder:
        now = now or utcnow()
        if appt.status == "cancelled":
            raise BookingError("That appointment was cancelled, so a follow-up can't be linked to it.", "not_active")
        due = datetime.combine(due_date, time(9, 0), tzinfo=sched.IST)
        if due <= now:
            raise BookingError("The follow-up date must be in the future.", "date_in_past")
        if due > now + timedelta(days=365):
            raise BookingError("Follow-up reminders can be set up to one year ahead.", "date_too_far")
        if await self.reminders.count_follow_ups(appt.id) >= 3:
            raise BookingError("This appointment already has 3 follow-up reminders.", "too_many_follow_ups")
        extra = f" Note: {note.strip()}" if note and note.strip() else ""
        return await self.reminders.add(
            user_id=appt.user_id, conversation_id=appt.conversation_id, appointment_id=appt.id, kind="follow_up", due_at=due,
            title="Follow-up visit due",
            message=f"Follow-up visit due after your appointment {appt.ref} with {appt.provider.name}.{extra} Tell me and I'll find you a slot.",
            language=appt.language, payload={"appointment_ref": appt.ref, "note": note},
        )

    async def record_feedback(self, appt: Appointment, rating: int, comment: str | None, now: datetime | None = None) -> Appointment:
        now = now or utcnow()
        if appt.status == "cancelled":
            raise BookingError("That appointment was cancelled, so there is nothing to rate.", "not_active")
        if appt.status != "completed" and appt.ends_at > now:
            raise BookingError("Feedback can be given after the appointment has taken place.", "too_early")
        if appt.feedback_rating is not None:
            raise BookingError("Feedback was already recorded for this appointment. Thank you!", "already_rated")
        appt.feedback_rating, appt.feedback_comment = rating, (comment or "").strip() or None
        for r in await self.reminders.pending_for_appointment(appt.id, ("feedback_request",)):
            r.status = "cancelled"
        await self.session.flush()
        await send_webhook(self.http, self.s, "appointment.feedback", {"reference": appt.ref, "rating": rating, "comment": appt.feedback_comment})
        return appt

    # ------------------------------------------------------------------ demo helpers (settings.demo_mode)
    async def demo_complete(self, appt: Appointment) -> Appointment:
        """Pretend the visit happened (a real system would be told by the hospital)."""
        if appt.status != "booked":
            raise BookingError(f"Appointment {appt.ref} is {appt.status}.", "not_active")
        appt.status = "completed"
        for r in await self.reminders.pending_for_appointment(appt.id, ("appointment_reminder",)):
            r.status = "cancelled"
        for r in await self.reminders.pending_for_appointment(appt.id, ("feedback_request",)):
            r.due_at = utcnow()
        await self.session.flush()
        return appt

    async def demo_remind_now(self, appt: Appointment) -> Reminder:
        when = sched.describe(appt.starts_at)
        return await self.reminders.add(
            user_id=appt.user_id, conversation_id=appt.conversation_id, appointment_id=appt.id, kind="appointment_reminder", due_at=utcnow(),
            title="Appointment reminder",
            message=f"Reminder: appointment {appt.ref} with {appt.provider.name} on {when['display']} for {appt.patient_name}.",
            language=appt.language, payload={"appointment_ref": appt.ref, "demo": True},
        )
