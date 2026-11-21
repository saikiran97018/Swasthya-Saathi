"""Tasks and service requests."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Task, utcnow

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I so refs are easy to read aloud


def _suffix(n: int = 5) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


class TaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _new_ref(self, kind: str) -> str:
        prefix = "SR" if kind == "service_request" else "T"
        stamp = utcnow().strftime("%y%m%d") if kind == "service_request" else ""
        for _ in range(10):
            ref = f"{prefix}-{stamp}-{_suffix()}" if stamp else f"{prefix}-{_suffix()}"
            if not await self.session.scalar(select(Task.id).where(Task.ref == ref)):
                return ref
        raise RuntimeError("could not allocate a unique reference")

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        title: str,
        description: str | None = None,
        kind: str = "task",
        status: str = "open",
        due_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Task:
        task = Task(
            user_id=user_id,
            conversation_id=conversation_id,
            ref=await self._new_ref(kind),
            kind=kind,
            title=title[:200],
            description=description,
            status=status,
            due_at=due_at,
            payload=payload or {},
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def get_by_ref(self, user_id: uuid.UUID, ref: str) -> Task | None:
        return await self.session.scalar(select(Task).where(Task.user_id == user_id, Task.ref == ref.strip().upper()))

    async def get_owned(self, user_id: uuid.UUID, task_id: uuid.UUID) -> Task | None:
        task = await self.session.get(Task, task_id)
        return task if task and task.user_id == user_id else None

    async def list_for_user(
        self, user_id: uuid.UUID, *, status: str | None = None, kind: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[Task], int]:
        stmt = select(Task).where(Task.user_id == user_id)
        if status:
            stmt = stmt.where(Task.status == status)
        if kind:
            stmt = stmt.where(Task.kind == kind)
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await self.session.execute(stmt.order_by(Task.created_at.desc()).limit(limit).offset(offset))).scalars().all()
        return list(rows), total

    async def count_by_status(self, user_id: uuid.UUID) -> dict[str, int]:
        rows = await self.session.execute(select(Task.status, func.count()).where(Task.user_id == user_id).group_by(Task.status))
        return {s: n for s, n in rows.all()}
