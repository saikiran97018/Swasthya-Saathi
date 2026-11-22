"""Daily medicine reminders.

The person says what to be reminded of ("my BP tablet") and at which times. We never suggest or check medicines or doses: the label is
their own words. Each time of day is one pending reminder; when it is delivered the next day's is created (see ReminderService), so
the series runs until its end date or until the person stops it. Reminders reach the app's bell and, if allowed, the phone.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Reminder, User, utcnow

IST = timezone(timedelta(hours=5, minutes=30))
KIND = "medicine"
MAX_SERIES = 10  # active reminders per person
MAX_TIMES = 4  # times per day
MAX_DAYS = 180
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class MedicineError(ValueError):
    def __init__(self, message: str, code: str = "invalid_medicine_reminder"):
        super().__init__(message)
        self.message, self.code = message, code


def clean_label(label: str | None) -> str:
    text = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", label or "").split())[:60]
    if len(text) < 2:
        raise MedicineError("Tell me what to remind you about, for example 'BP tablet'.")
    return text


def clean_times(times: list[str] | None) -> list[str]:
    out: list[str] = []
    for t in times or []:
        t = (t or "").strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", t)
        if m:
            t = f"{int(m.group(1)):02d}:{m.group(2)}"
        if not TIME_RE.match(t):
            raise MedicineError(f"'{t}' is not a time. Use 24-hour times such as 08:00 or 20:30.")
        if t not in out:
            out.append(t)
    if not out:
        raise MedicineError("At least one time is needed, for example 08:00.")
    if len(out) > MAX_TIMES:
        raise MedicineError(f"At most {MAX_TIMES} times a day.")
    return sorted(out)


def next_occurrence(hhmm: str, now: datetime | None = None) -> datetime:
    """The next time the clock (in IST) shows hhmm, at least a minute from now, as UTC."""
    now = now or utcnow()
    h, m = int(hhmm[:2]), int(hhmm[3:])
    local = now.astimezone(IST)
    candidate = datetime.combine(local.date(), time(h, m), tzinfo=IST)
    if candidate <= local + timedelta(minutes=1):
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


class MedicineService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _pending(self, user_id) -> list[Reminder]:
        rows = (await self.session.scalars(select(Reminder).where(Reminder.user_id == user_id, Reminder.kind == KIND, Reminder.status == "pending").order_by(Reminder.due_at))).all()
        return list(rows)

    async def create(self, user: User, *, label: str, times: list[str], days: int, language: str) -> dict:
        label, times = clean_label(label), clean_times(times)
        if not 1 <= days <= MAX_DAYS:
            raise MedicineError(f"Choose between 1 and {MAX_DAYS} days.")
        if len({r.payload.get("series") for r in await self._pending(user.id)}) >= MAX_SERIES:
            raise MedicineError(f"You already have {MAX_SERIES} medicine reminders. Stop one first.", code="too_many_medicine_reminders")
        series = uuid.uuid4().hex[:12]
        now = utcnow()
        firsts = {t: next_occurrence(t, now) for t in times}
        start: date = min(d.astimezone(IST).date() for d in firsts.values())  # day one = the day of the first dose
        ends_on: date = start + timedelta(days=days - 1)
        for t, due in firsts.items():
            if due.astimezone(IST).date() > ends_on:
                continue  # a later time of day whose first dose would fall after the last day
            self.session.add(Reminder(
                user_id=user.id, kind=KIND, due_at=due, title="Medicine reminder", message=f"Time to take your {label}.", language=language or "en",
                payload={"series": series, "label": label, "time": t, "repeat": "daily", "ends_on": ends_on.isoformat()},
            ))
        await self.session.flush()
        return {"series": series, "label": label, "times": times, "ends_on": ends_on.isoformat()}

    async def list(self, user_id) -> list[dict]:
        groups: dict[str, dict] = {}
        for r in await self._pending(user_id):
            p = r.payload or {}
            g = groups.setdefault(p.get("series", r.id.hex), {"series": p.get("series", r.id.hex), "label": p.get("label", "Medicine"), "times": [], "ends_on": p.get("ends_on"), "next_due": r.due_at})
            if p.get("time") and p["time"] not in g["times"]:
                g["times"].append(p["time"])
            g["next_due"] = min(g["next_due"], r.due_at)
        for g in groups.values():
            g["times"].sort()
        return sorted(groups.values(), key=lambda g: g["next_due"])

    async def stop(self, user_id, *, series: str | None = None, label: str | None = None) -> int:
        """Stop one reminder (by id or by words from its label). Returns how many reminders were stopped (0 = none matched)."""
        n = 0
        needle = (label or "").strip().lower()
        for r in await self._pending(user_id):
            p = r.payload or {}
            if (series and p.get("series") == series) or (needle and needle in str(p.get("label", "")).lower()):
                r.status = "cancelled"
                n += 1
        await self.session.flush()
        return n


def following_dose(r: Reminder, now: datetime) -> Reminder | None:
    """The next day's reminder for a delivered one in a daily series, or None when the series is over."""
    p = r.payload or {}
    if r.kind != KIND or p.get("repeat") != "daily":
        return None
    due = r.due_at + timedelta(days=1)
    while due <= now:  # the server was off for a while: skip doses that are already in the past
        due += timedelta(days=1)
    if p.get("ends_on") and due.astimezone(IST).date().isoformat() > p["ends_on"]:
        return None
    return Reminder(user_id=r.user_id, kind=KIND, due_at=due, title=r.title, message=r.message, language=r.language, payload=dict(p))
