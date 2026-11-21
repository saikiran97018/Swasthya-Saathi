"""Healthcare provider directory queries."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Appointment, Provider
from app.services.scheduling import normalise_city


class ProviderRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def is_empty(self) -> bool:
        return (await self.session.execute(select(Provider.id).limit(1))).first() is None

    async def add(self, **fields) -> Provider:
        p = Provider(**fields)
        self.session.add(p)
        await self.session.flush()
        return p

    async def get_by_code(self, code: str) -> Provider | None:
        return await self.session.scalar(select(Provider).where(Provider.code == code.strip().upper(), Provider.active.is_(True)))

    async def get(self, provider_id) -> Provider | None:
        return await self.session.get(Provider, provider_id)

    async def cities(self) -> list[str]:
        rows = await self.session.execute(select(Provider.city).where(Provider.active.is_(True), Provider.source != "osm").distinct().order_by(Provider.city))
        return [r[0] for r in rows.all()]

    async def get_or_create_from_place(self, place, fallback_city: str | None = None) -> Provider:
        """The row that a visit to a real (OpenStreetMap) place points at. It has no schedule and no online slots."""
        existing = await self.session.scalar(select(Provider).where(Provider.osm_id == place.osm_key))
        if existing is not None:
            # keep the details fresh: a phone number may have been added on OpenStreetMap since
            existing.name, existing.address, existing.phone = place.name[:200], place.address, place.phone
            existing.website, existing.opening_hours, existing.active = place.website, place.opening_hours, True
            return existing
        row = Provider(
            code=place.provider_code, name=place.name[:200], kind=place.kind if place.kind in ("hospital", "clinic", "phc") else "clinic",
            doctor_name=None, specialties=list(place.specialties), city=(place.city or fallback_city or "")[:80], state="", address=place.address,
            phone=place.phone, languages=[], schedule=[], slot_minutes=30, fee_inr=0, accepts_ayushman=False, teleconsultation=False,
            is_demo=False, active=True, source="osm", osm_id=place.osm_key, lat=place.lat, lon=place.lon, website=place.website,
            opening_hours=place.opening_hours,
        )
        try:
            async with self.session.begin_nested():  # two people planning a visit to the same new place at once: the second reuses the row
                self.session.add(row)
                await self.session.flush()
        except IntegrityError:
            return await self.session.scalar(select(Provider).where(Provider.osm_id == place.osm_key))
        return row

    async def search(
        self,
        *,
        specialty: str | None = None,
        city: str | None = None,
        language: str | None = None,
        kind: str | None = None,
        teleconsultation: bool | None = None,
        accepts_ayushman: bool | None = None,
        limit: int = 6,
    ) -> list[Provider]:
        """Small curated directory -> filter in Python (works identically on PostgreSQL and SQLite)."""
        rows = (await self.session.execute(select(Provider).where(Provider.active.is_(True), Provider.source != "osm").order_by(Provider.city, Provider.name))).scalars().all()
        wanted_city = normalise_city(city)
        out: list[Provider] = []
        for p in rows:
            if wanted_city and wanted_city not in p.city.lower():
                continue
            if specialty and specialty.lower() not in [s.lower() for s in p.specialties]:
                continue
            if language and language not in (p.languages or []):
                continue
            if kind and p.kind != kind:
                continue
            if teleconsultation is not None and p.teleconsultation != teleconsultation:
                continue
            if accepts_ayushman is not None and p.accepts_ayushman != accepts_ayushman:
                continue
            out.append(p)
        return out[:limit]

    async def ratings(self, provider_ids: list) -> dict:
        """{provider_id: (average rating, number of ratings)} from real patient feedback only."""
        if not provider_ids:
            return {}
        rows = await self.session.execute(
            select(Appointment.provider_id, func.avg(Appointment.feedback_rating), func.count(Appointment.feedback_rating))
            .where(Appointment.provider_id.in_(provider_ids), Appointment.feedback_rating.is_not(None))
            .group_by(Appointment.provider_id)
        )
        return {pid: (float(avg), int(n)) for pid, avg, n in rows.all()}
