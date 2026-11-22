"""Symptom check-in: the day after someone tells Saathi how they feel, a notification asks how they are now.

Only for routine and urgent symptoms (an emergency gets "call 112", not a reminder), only when the person has not switched it off in
Settings, and never more than one waiting at a time. Tapping it opens the same chat with a draft, so the assistant knows the history and
re-checks the urgency.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Conversation, Reminder, User, UserPreference, utcnow

KIND = "symptom_checkin"
IST = timezone(timedelta(hours=5, minutes=30))
AFTER = timedelta(hours=24)


def checkin_time(now: datetime) -> datetime:
    """24 hours later, but never in the middle of the night: 22:00 to 07:00 IST moves to 08:00."""
    due = now + AFTER
    local = due.astimezone(IST)
    if local.hour >= 22:
        local = datetime.combine(local.date() + timedelta(days=1), time(8, 0), tzinfo=IST)
    elif local.hour < 7:
        local = datetime.combine(local.date(), time(8, 0), tzinfo=IST)
    return local.astimezone(timezone.utc)


async def schedule_checkin(session: AsyncSession, user: User, conversation: Conversation, *, symptoms: str, urgency: str, language: str) -> Reminder | None:
    if urgency == "emergency" or len((symptoms or "").strip()) < 3:
        return None
    prefs = await session.scalar(select(UserPreference).where(UserPreference.user_id == user.id))
    if prefs is not None and not prefs.symptom_checkins:
        return None
    for old in (await session.scalars(select(Reminder).where(Reminder.user_id == user.id, Reminder.kind == KIND, Reminder.status == "pending"))).all():
        old.status = "cancelled"  # one waiting check-in at a time: the newest symptoms replace the old ones
    short = " ".join(symptoms.split())[:80]
    r = Reminder(
        user_id=user.id, conversation_id=conversation.id, kind=KIND, due_at=checkin_time(utcnow()), title="How are you feeling?",
        message=f"You told me about: {short}. How are you feeling now? Tap to tell me.", language=language or "en", payload={"symptoms": short, "urgency": urgency},
    )
    session.add(r)
    await session.flush()
    return r
