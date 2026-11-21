"""Appointment and reminder persistence."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Appointment, Reminder, utcnow

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class AppointmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def new_ref(self) -> str:
        for _ in range(10):
            ref = "AP-" + "".join(secrets.choice(_ALPHABET) for _ in range(5))
            if not await self.session.scalar(select(Appointment.id).where(Appointment.ref == ref)):
                return ref
        raise RuntimeError("could not allocate an appointment reference")

    def _base(self):
        return select(Appointment).options(selectinload(Appointment.provider), selectinload(Appointment.family_member))

    async def get_by_ref(self, user_id: uuid.UUID, ref: str) -> Appointment | None:
        return await self.session.scalar(self._base().where(Appointment.user_id == user_id, Appointment.ref == ref.strip().upper()))

    async def get_owned(self, user_id: uuid.UUID, appointment_id: uuid.UUID) -> Appointment | None:
        appt = await self.session.scalar(self._base().where(Appointment.id == appointment_id))
        return appt if appt and appt.user_id == user_id else None

    async def list_for_user(
        self, user_id: uuid.UUID, *, scope: str = "upcoming", now: datetime | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[Appointment], int]:
        now = now or utcnow()
        stmt = self._base().where(Appointment.user_id == user_id)
        if scope == "upcoming":
            stmt = stmt.where(Appointment.status == "booked", Appointment.ends_at >= now).order_by(Appointment.starts_at)
        elif scope == "past":
            stmt = stmt.where(or_(Appointment.status != "booked", Appointment.ends_at < now)).order_by(Appointment.starts_at.desc())
        else:
            stmt = stmt.order_by(Appointment.starts_at.desc())
        total = (await self.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
        rows = (await self.session.execute(stmt.limit(limit).offset(offset))).scalars().all()
        return list(rows), total

    async def booked_starts(self, provider_id: uuid.UUID, start: datetime, end: datetime) -> set[datetime]:
        rows = await self.session.execute(
            select(Appointment.starts_at).where(
                Appointment.provider_id == provider_id, Appointment.status == "booked", Appointment.starts_at >= start, Appointment.starts_at <= end
            )
        )
        return {r[0] for r in rows.all()}

    async def user_conflict(
        self, user_id: uuid.UUID, starts_at: datetime, ends_at: datetime, exclude_id: uuid.UUID | None = None, family_member_id: uuid.UUID | None = None
    ) -> Appointment | None:
        """An overlapping booking for the SAME patient (the account holder, or one family member): a parent and a child may
        well see different doctors at the same time."""
        stmt = self._base().where(
            Appointment.user_id == user_id, Appointment.status == "booked",
            and_(Appointment.starts_at < ends_at, Appointment.ends_at > starts_at),
        )
        stmt = stmt.where(Appointment.family_member_id.is_(None) if family_member_id is None else Appointment.family_member_id == family_member_id)
        if exclude_id:
            stmt = stmt.where(Appointment.id != exclude_id)
        return await self.session.scalar(stmt.limit(1))

    async def count_active(self, user_id: uuid.UUID, now: datetime | None = None) -> int:
        now = now or utcnow()
        return (
            await self.session.execute(
                select(func.count()).select_from(Appointment).where(Appointment.user_id == user_id, Appointment.status == "booked", Appointment.ends_at >= now)
            )
        ).scalar_one()


class ReminderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, **fields) -> Reminder:
        r = Reminder(**fields)
        self.session.add(r)
        await self.session.flush()
        return r

    async def pending_for_appointment(self, appointment_id: uuid.UUID, kinds: tuple[str, ...] | None = None) -> list[Reminder]:
        stmt = select(Reminder).where(Reminder.appointment_id == appointment_id, Reminder.status == "pending")
        if kinds:
            stmt = stmt.where(Reminder.kind.in_(kinds))
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_appointment(self, appointment_id: uuid.UUID) -> list[Reminder]:
        rows = await self.session.execute(select(Reminder).where(Reminder.appointment_id == appointment_id).order_by(Reminder.due_at))
        return list(rows.scalars().all())

    async def count_follow_ups(self, appointment_id: uuid.UUID) -> int:
        return (
            await self.session.execute(
                select(func.count()).select_from(Reminder).where(Reminder.appointment_id == appointment_id, Reminder.kind == "follow_up", Reminder.status != "cancelled")
            )
        ).scalar_one()

    async def notifications(self, user_id: uuid.UUID, *, unread_only: bool = False, limit: int = 30, offset: int = 0) -> tuple[list[Reminder], int, int]:
        base = select(Reminder).where(Reminder.user_id == user_id, Reminder.status == "delivered")
        unread = (await self.session.execute(select(func.count()).select_from(base.where(Reminder.read_at.is_(None)).subquery()))).scalar_one()
        stmt = base.where(Reminder.read_at.is_(None)) if unread_only else base
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await self.session.execute(stmt.order_by(Reminder.delivered_at.desc()).limit(limit).offset(offset))).scalars().all()
        return list(rows), total, unread

    async def get_owned(self, user_id: uuid.UUID, reminder_id: uuid.UUID) -> Reminder | None:
        r = await self.session.get(Reminder, reminder_id)
        return r if r and r.user_id == user_id else None

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        rows = (await self.session.execute(select(Reminder).where(Reminder.user_id == user_id, Reminder.status == "delivered", Reminder.read_at.is_(None)))).scalars().all()
        for r in rows:
            r.read_at = utcnow()
        await self.session.flush()
        return len(rows)
