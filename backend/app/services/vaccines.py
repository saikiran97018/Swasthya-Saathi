"""Child vaccination tracker, following India's Universal Immunisation Programme (UIP) schedule.

The schedule is a general guide: a doctor, ASHA worker or the child's immunisation card decides the exact doses (catch-up rules, local
programmes such as JE and extra vaccines). The app only shows what is due and when, lets the parent mark a visit as done, and reminds them.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import FamilyMember, Reminder, User, VaccinationMilestone, utcnow

IST = timezone(timedelta(hours=5, minutes=30))
KIND = "vaccine"
SCHEDULE_NAME = "India's Universal Immunisation Programme"
MAX_AGE_YEARS = 17  # the schedule ends with the 16-year Td dose
REMIND_DAYS_BEFORE = 3
FUTURE_REMINDERS = 2  # only the next two upcoming visits are reminded, so a new baby's whole schedule is not dumped at once


@dataclass(frozen=True)
class Milestone:
    key: str
    label: str
    months: int  # age in months when it falls due (weeks are given as days)
    days: int
    vaccines: tuple[str, ...]
    grace_days: int  # how long after the due date before it counts as overdue
    note: str = ""


MILESTONES: tuple[Milestone, ...] = (
    Milestone("birth", "At birth", 0, 0, ("BCG", "OPV 0 (oral polio)", "Hepatitis B (birth dose)"), 14, "Hepatitis B is best within 24 hours of birth."),
    Milestone("6w", "6 weeks", 0, 42, ("OPV 1", "Pentavalent 1", "Rotavirus 1", "fIPV 1", "PCV 1"), 28),
    Milestone("10w", "10 weeks", 0, 70, ("OPV 2", "Pentavalent 2", "Rotavirus 2"), 28),
    Milestone("14w", "14 weeks", 0, 98, ("OPV 3", "Pentavalent 3", "Rotavirus 3", "fIPV 2", "PCV 2"), 28),
    Milestone("9m", "9 months", 9, 0, ("Measles-Rubella 1", "fIPV 3", "PCV booster", "Vitamin A (first dose)", "JE 1 (where recommended)"), 90),
    Milestone("16m", "16 to 24 months", 16, 0, ("Measles-Rubella 2", "DPT booster 1", "OPV booster", "JE 2 (where recommended)", "Vitamin A"), 240),
    Milestone("5y", "5 to 6 years", 60, 0, ("DPT booster 2",), 365),
    Milestone("10y", "10 years", 120, 0, ("Td (tetanus and diphtheria)",), 365),
    Milestone("16y", "16 years", 192, 0, ("Td (tetanus and diphtheria)",), 365),
)
KEYS = {m.key for m in MILESTONES}
DISCLAIMER = f"A general guide based on {SCHEDULE_NAME}. Your doctor or ASHA worker may change it: always follow the child's immunisation card."


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def due_date(birth: date, m: Milestone) -> date:
    return add_months(birth, m.months) + timedelta(days=m.days)


def age_years(birth: date, today: date) -> int:
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def eligible(birth: date | None, today: date) -> bool:
    return birth is not None and birth <= today and age_years(birth, today) < MAX_AGE_YEARS


def schedule(birth: date, today: date, given: dict[str, date]) -> list[dict]:
    """Every milestone with its due date and status: given | overdue | due | upcoming."""
    out = []
    for m in MILESTONES:
        due = due_date(birth, m)
        if m.key in given:
            status = "given"
        elif today > due + timedelta(days=m.grace_days):
            status = "overdue"
        elif today >= due:
            status = "due"
        else:
            status = "upcoming"
        out.append({"key": m.key, "label": m.label, "vaccines": list(m.vaccines), "due_on": due, "status": status, "given_on": given.get(m.key), "note": m.note})
    return out


def pending(items: list[dict]) -> list[dict]:
    return [i for i in items if i["status"] != "given"]


def focus(items: list[dict], today: date) -> dict | None:
    """The one to talk about: the oldest overdue or due visit, else the next upcoming one."""
    open_ = pending(items)
    now = [i for i in open_ if i["status"] in ("overdue", "due")]
    return now[0] if now else next((i for i in open_ if i["due_on"] >= today), None)


def _nine_am(d: date) -> datetime:
    return datetime.combine(d, time(9, 0), tzinfo=IST).astimezone(timezone.utc)


class VaccinationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def given(self, member_id) -> dict[str, date]:
        rows = (await self.session.scalars(select(VaccinationMilestone).where(VaccinationMilestone.family_member_id == member_id))).all()
        return {r.milestone: r.given_on for r in rows}

    async def mark(self, member: FamilyMember, milestone: str, given_on: date | None) -> None:
        row = await self.session.scalar(select(VaccinationMilestone).where(VaccinationMilestone.family_member_id == member.id, VaccinationMilestone.milestone == milestone))
        if given_on is None:
            if row is not None:
                await self.session.delete(row)
        elif row is None:
            self.session.add(VaccinationMilestone(family_member_id=member.id, milestone=milestone, given_on=given_on))
        else:
            row.given_on = given_on
        await self.session.flush()

    async def cancel_reminders(self, member_id) -> None:
        for r in (await self.session.scalars(select(Reminder).where(Reminder.kind == KIND, Reminder.status == "pending"))).all():
            if (r.payload or {}).get("member_id") == str(member_id):
                r.status = "cancelled"

    async def sync_reminders(self, user: User, member: FamilyMember, language: str, today: date | None = None) -> int:
        """Replace this child's pending vaccine reminders with the right ones. Returns how many were created."""
        today = today or utcnow().astimezone(IST).date()
        await self.cancel_reminders(member.id)
        if not eligible(member.birth_date, today):
            return 0
        items = schedule(member.birth_date, today, await self.given(member.id))  # type: ignore[arg-type]
        now, made = utcnow(), 0
        first = focus(items, today)
        chosen: list[tuple[dict, datetime]] = []
        if first and first["status"] in ("overdue", "due"):
            chosen.append((first, max(_nine_am(today + timedelta(days=1)), now + timedelta(minutes=1))))  # tomorrow morning
        for i in [x for x in pending(items) if x["status"] == "upcoming"][:FUTURE_REMINDERS]:
            chosen.append((i, max(_nine_am(i["due_on"] - timedelta(days=REMIND_DAYS_BEFORE)), now + timedelta(minutes=1))))
        for item, when in chosen:
            self.session.add(Reminder(
                user_id=user.id, kind=KIND, due_at=when, title="Vaccination due", language=language or "en",
                message=f"{member.name}: vaccines due at {item['label']} ({', '.join(item['vaccines'][:4])}). Tap to plan a visit.",
                payload={"member_id": str(member.id), "milestone": item["key"]},
            ))
            made += 1
        await self.session.flush()
        return made

    async def due_summary(self, user_id, today: date | None = None, limit: int = 2) -> str:
        """One line for the assistant's context: which children have vaccines due or coming up."""
        today = today or utcnow().astimezone(IST).date()
        members = (await self.session.scalars(select(FamilyMember).where(FamilyMember.user_id == user_id, FamilyMember.birth_date.is_not(None)).order_by(FamilyMember.name))).all()
        lines = []
        for m in members:
            if not eligible(m.birth_date, today):
                continue
            item = focus(schedule(m.birth_date, today, await self.given(m.id)), today)  # type: ignore[arg-type]
            if item and (item["status"] != "upcoming" or (item["due_on"] - today).days <= 60):
                when = "due now" if item["status"] in ("due", "overdue") else f"due {item['due_on'].strftime('%d %b')}"
                lines.append(f"{m.name}: {item['label']} ({', '.join(item['vaccines'][:3])}) {when}")
            if len(lines) >= limit:
                break
        return ("Child vaccines (UIP guide): " + "; ".join(lines) + ".") if lines else ""
