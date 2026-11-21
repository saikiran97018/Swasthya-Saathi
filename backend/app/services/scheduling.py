"""Appointment slot maths: weekly schedules -> concrete slots (all clinic times are IST)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))
MIN_LEAD = timedelta(minutes=30)  # can't book a slot that starts in less than 30 minutes

SPECIALTIES = (
    "general medicine", "pediatrics", "gynecology", "dermatology", "cardiology",
    "orthopedics", "ophthalmology", "ent", "dentistry", "psychiatry",
)

CITY_ALIASES = {
    "bangalore": "bengaluru", "bombay": "mumbai", "madras": "chennai", "calcutta": "kolkata",
    "cochin": "kochi", "vizag": "visakhapatnam", "poona": "pune", "new delhi": "delhi",
}


def normalise_city(city: str | None) -> str | None:
    if not city or not city.strip():
        return None
    c = " ".join(city.lower().split())
    return CITY_ALIASES.get(c, c)


def to_ist(dt: datetime) -> datetime:
    return dt.astimezone(IST)


def parse_local_slot(raw: str) -> datetime:
    """Parse 'YYYY-MM-DD HH:MM' (or ISO 8601) as IST (unless an offset is given). Returns an aware datetime."""
    text = raw.strip().replace("T", " ")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("Time must look like 'YYYY-MM-DD HH:MM' in Indian time, e.g. 2026-11-22 10:20") from exc
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt


def describe(dt: datetime) -> dict[str, str]:
    """Human-friendly pieces of a local time, for tool results and reminders."""
    l = to_ist(dt)
    return {
        "date": l.strftime("%Y-%m-%d"),
        "day": l.strftime("%A"),
        "time": l.strftime("%H:%M"),
        "display": l.strftime("%A, %d %B %Y, ") + l.strftime("%I:%M %p").lstrip("0"),
    }


def _windows_for(provider_schedule: list[dict[str, Any]], day: date):
    for w in provider_schedule:
        if day.weekday() in w.get("days", []):
            yield (
                time.fromisoformat(w["start"]),
                time.fromisoformat(w["end"]),
            )


def slots_on(provider_schedule: list[dict[str, Any]], slot_minutes: int, day: date) -> list[datetime]:
    out: list[datetime] = []
    step = timedelta(minutes=slot_minutes)
    for start, end in _windows_for(provider_schedule, day):
        cur = datetime.combine(day, start, tzinfo=IST)
        limit = datetime.combine(day, end, tzinfo=IST)
        while cur + step <= limit:
            out.append(cur)
            cur += step
    return sorted(set(out))


def is_on_grid(provider_schedule: list[dict[str, Any]], slot_minutes: int, dt: datetime) -> bool:
    l = to_ist(dt)
    return l.replace(second=0, microsecond=0) in set(slots_on(provider_schedule, slot_minutes, l.date()))


def bookable_window(now: datetime, horizon_days: int) -> tuple[datetime, datetime]:
    return now + MIN_LEAD, now + timedelta(days=horizon_days)
