"""Family members and emergency contacts."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import EmergencyContact, FamilyMember, Provider

MAX_FAMILY_MEMBERS = 8
MAX_EMERGENCY_CONTACTS = 5


class FamilyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self, user_id: uuid.UUID) -> list[FamilyMember]:
        rows = await self.session.execute(select(FamilyMember).where(FamilyMember.user_id == user_id).order_by(FamilyMember.created_at, FamilyMember.id))
        return list(rows.scalars().all())

    async def count(self, user_id: uuid.UUID) -> int:
        return (await self.session.execute(select(func.count()).select_from(FamilyMember).where(FamilyMember.user_id == user_id))).scalar_one()

    async def get_owned(self, user_id: uuid.UUID, member_id: uuid.UUID) -> FamilyMember | None:
        m = await self.session.get(FamilyMember, member_id)
        return m if m and m.user_id == user_id else None

    async def find_by_name(self, user_id: uuid.UUID, name: str) -> FamilyMember | None:
        """Case-insensitive exact name match among this user's members (the agent links a booking to a profile this way)."""
        wanted = " ".join(name.split()).lower()
        for m in await self.list(user_id):
            if m.name.lower() == wanted:
                return m
        return None

    async def add(self, **fields) -> FamilyMember:
        m = FamilyMember(**fields)
        self.session.add(m)
        await self.session.flush()
        return m

    async def delete(self, member: FamilyMember) -> None:
        await self.session.delete(member)
        await self.session.flush()


class EmergencyContactRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self, user_id: uuid.UUID) -> list[EmergencyContact]:
        rows = await self.session.execute(select(EmergencyContact).where(EmergencyContact.user_id == user_id).order_by(EmergencyContact.created_at, EmergencyContact.id))
        return list(rows.scalars().all())

    async def count(self, user_id: uuid.UUID) -> int:
        return (await self.session.execute(select(func.count()).select_from(EmergencyContact).where(EmergencyContact.user_id == user_id))).scalar_one()

    async def get_owned(self, user_id: uuid.UUID, contact_id: uuid.UUID) -> EmergencyContact | None:
        c = await self.session.get(EmergencyContact, contact_id)
        return c if c and c.user_id == user_id else None

    async def add(self, **fields) -> EmergencyContact:
        c = EmergencyContact(**fields)
        self.session.add(c)
        await self.session.flush()
        return c

    async def delete(self, contact: EmergencyContact) -> None:
        await self.session.delete(contact)
        await self.session.flush()


async def emergency_capable_providers(session: AsyncSession, city: str, limit: int = 6) -> list[Provider]:
    """Hospitals and primary health centres in a city (hospitals first). Teleconsultation-only services are not 'nearby'."""
    city = " ".join(city.split()).lower()
    if not city:
        return []
    stmt = (
        select(Provider)
        .where(Provider.active.is_(True), Provider.source != "osm", Provider.kind.in_(("hospital", "phc")), func.lower(Provider.city) == city)
        .order_by(Provider.name)
        .limit(50)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    rows.sort(key=lambda p: (0 if p.kind == "hospital" else 1, p.name))
    return rows[:limit]
