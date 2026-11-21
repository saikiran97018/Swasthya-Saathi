"""Delivers due reminders (in-app notifications) and marks finished appointments as completed.

A background loop calls `deliver_due()` every REMINDER_POLL_SECONDS. Delivered reminders are shown in the
app's notification bell and are also POSTed to the integration webhook, so an SMS/WhatsApp gateway can
send them. When the user's language is not English the text is translated with the LLM (falling back to
English if the LLM is unavailable).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.database.connection import get_session_factory
from app.database.models import Appointment, Reminder, utcnow
from app.services.llm_service import LLMService
from app.services.webhooks import send_webhook
from app.utils.language import language_name

log = logging.getLogger("app.reminders")

_TRANSLATE_PROMPT = (
    "Translate the message into {lang}, written in that language's native script, for a patient who will hear it spoken aloud. "
    "Keep names, numbers, dates, times and reference codes (like AP-7K3QX) exactly as they are. Output only the translation."
)


class ReminderService:
    def __init__(self, settings: Settings, llm: LLMService, http):
        self.s, self.llm, self.http = settings, llm, http

    async def _localise(self, r: Reminder) -> str:
        if r.language == "en" or not self.llm.configured:
            return r.message
        try:
            text = await asyncio.wait_for(
                self.llm.complete(
                    [{"role": "system", "content": _TRANSLATE_PROMPT.format(lang=language_name(r.language))}, {"role": "user", "content": r.message}],
                    temperature=0.1, max_tokens=300,
                ),
                timeout=15,
            )
            return text or r.message
        except Exception as exc:
            log.info("reminder translation skipped: %s", type(exc).__name__)
            return r.message

    async def deliver_due(self, now: datetime | None = None) -> int:
        """Deliver every pending reminder due at `now`. Returns how many were delivered."""
        now = now or utcnow()
        delivered = 0
        async with get_session_factory()() as session:
            # Claim finished visits the same way as reminders (stable order + SKIP LOCKED): concurrent workers never wait on
            # or deadlock over the same rows; whichever worker got there first completes them.
            finished = await session.scalars(
                select(Appointment)
                .where(Appointment.status == "booked", Appointment.ends_at < now)
                .order_by(Appointment.id)
                .with_for_update(skip_locked=True)
            )
            for appt in finished:
                appt.status = "completed"

            # FOR UPDATE SKIP LOCKED: with several workers each running this loop, a reminder row is claimed by exactly one of
            # them (the others skip it), so nothing is delivered twice. SQLite has no row locks and ignores the clause.
            due = (
                await session.scalars(
                    select(Reminder)
                    .where(Reminder.status == "pending", Reminder.due_at <= now)
                    .order_by(Reminder.due_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for r in due:
                appt = await session.scalar(select(Appointment).options(selectinload(Appointment.provider)).where(Appointment.id == r.appointment_id)) if r.appointment_id else None
                if appt and appt.status == "cancelled":
                    r.status = "cancelled"
                    continue
                if appt and r.kind == "appointment_reminder" and appt.starts_at <= now:
                    r.status = "cancelled"  # the visit time has passed: a stale "you have an appointment soon" would confuse
                    continue
                r.delivered_message = await self._localise(r)
                r.status, r.delivered_at = "delivered", now
                await send_webhook(self.http, self.s, "reminder.delivered", {"kind": r.kind, "title": r.title, "message": r.delivered_message, "language": r.language, "appointment_ref": r.payload.get("appointment_ref")})
                delivered += 1
            await session.commit()
        if delivered:
            log.info("delivered %d reminder(s)", delivered)
        return delivered

    async def run_forever(self) -> None:
        while True:
            try:
                await self.deliver_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("reminder loop iteration failed")
            await asyncio.sleep(max(5, self.s.reminder_poll_seconds))
