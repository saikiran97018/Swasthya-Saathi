"""Users, preferences and language preferences."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import LanguagePreference, User, UserPreference


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, display_name: str, email: str | None = None, password_hash: str | None = None, is_guest: bool = False) -> User:
        user = User(display_name=display_name, email=email, password_hash=password_hash, is_guest=is_guest)
        user.preferences = UserPreference()
        user.languages = [LanguagePreference(language_code="en", is_primary=True)]
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email.lower()))

    async def get_preferences(self, user_id: uuid.UUID) -> UserPreference:
        prefs = await self.session.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
        if prefs is None:
            prefs = UserPreference(user_id=user_id)
            self.session.add(prefs)
            await self.session.flush()
        return prefs

    async def get_languages(self, user_id: uuid.UUID) -> list[LanguagePreference]:
        rows = await self.session.execute(
            select(LanguagePreference).where(LanguagePreference.user_id == user_id).order_by(LanguagePreference.is_primary.desc(), LanguagePreference.language_code)
        )
        return list(rows.scalars().all())

    async def primary_language(self, user_id: uuid.UUID) -> str:
        langs = await self.get_languages(user_id)
        for l in langs:
            if l.is_primary:
                return l.language_code
        return langs[0].language_code if langs else "en"

    async def set_languages(self, user_id: uuid.UUID, primary: str, others: list[str]) -> list[LanguagePreference]:
        existing = {l.language_code: l for l in await self.get_languages(user_id)}
        wanted = [primary] + [c for c in others if c != primary]
        for code, row in list(existing.items()):
            if code not in wanted:
                await self.session.delete(row)
        for code in wanted:
            row = existing.get(code)
            if row is None:
                row = LanguagePreference(user_id=user_id, language_code=code)
                self.session.add(row)
            row.is_primary = code == primary
        await self.session.flush()
        return await self.get_languages(user_id)
