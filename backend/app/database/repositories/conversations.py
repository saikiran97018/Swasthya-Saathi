"""Conversation, message and metadata persistence."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.database.models import Conversation, ConversationMetadata, Message, ToolExecutionLog, utcnow


def _like_escape(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ---- conversations ---------------------------------------------------------------------
    async def create(self, user_id: uuid.UUID, *, title: str = "New conversation", language: str = "en", title_is_auto: bool = True) -> Conversation:
        conv = Conversation(user_id=user_id, title=title, language=language, title_is_auto=title_is_auto)
        conv.meta = ConversationMetadata(message_count=0, voice_message_count=0, extra={})
        self.session.add(conv)
        await self.session.flush()
        return conv

    async def get_owned(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation:
        conv = await self.session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            raise NotFound("Conversation not found", code="conversation_not_found")
        return conv

    async def list_for_user(self, user_id: uuid.UUID, *, q: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[Conversation], int]:
        stmt = select(Conversation).where(Conversation.user_id == user_id, Conversation.archived.is_(False))
        if q and q.strip():
            pattern = f"%{_like_escape(q.strip())}%"
            in_messages = select(Message.conversation_id).where(Message.content.ilike(pattern, escape="\\"))
            stmt = stmt.where(or_(Conversation.title.ilike(pattern, escape="\\"), Conversation.id.in_(in_messages)))
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (
            await self.session.execute(stmt.order_by(Conversation.last_message_at.desc()).limit(limit).offset(offset))
        ).scalars().all()
        return list(rows), total

    async def rename(self, conv: Conversation, title: str) -> Conversation:
        conv.title = title.strip()[:200] or conv.title
        conv.title_is_auto = False
        await self.session.flush()
        return conv

    async def delete(self, conv: Conversation) -> None:
        await self.session.delete(conv)
        await self.session.flush()

    async def get_meta(self, conv: Conversation) -> ConversationMetadata:
        meta = await self.session.scalar(select(ConversationMetadata).where(ConversationMetadata.conversation_id == conv.id))
        if meta is None:
            meta = ConversationMetadata(conversation_id=conv.id, message_count=0, voice_message_count=0, extra={})
            self.session.add(meta)
            await self.session.flush()
        return meta

    # ---- messages ---------------------------------------------------------------------------
    async def add_message(
        self,
        conv: Conversation,
        *,
        role: str,
        content: str = "",
        language: str | None = None,
        input_mode: str = "text",
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Message:
        last_seq = (
            await self.session.execute(select(func.max(Message.seq)).where(Message.conversation_id == conv.id))
        ).scalar_one()
        msg = Message(
            conversation_id=conv.id,
            seq=(last_seq or 0) + 1,
            role=role,
            content=content,
            language=language,
            input_mode=input_mode,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            meta=meta or {},
        )
        self.session.add(msg)

        conv.last_message_at = utcnow()
        if role in ("user", "assistant"):
            m = await self.get_meta(conv)
            m.message_count = (m.message_count or 0) + 1
            if role == "user" and input_mode == "voice":
                m.voice_message_count = (m.voice_message_count or 0) + 1
        await self.session.flush()
        return msg

    async def list_messages(self, conversation_id: uuid.UUID, *, after_seq: int = 0, limit: int | None = None) -> list[Message]:
        stmt = select(Message).where(Message.conversation_id == conversation_id, Message.seq > after_seq).order_by(Message.seq)
        if limit:
            # take the most recent `limit` messages, return in chronological order
            stmt = (
                select(Message)
                .where(Message.conversation_id == conversation_id, Message.seq > after_seq)
                .order_by(Message.seq.desc())
                .limit(limit)
            )
            rows = list((await self.session.execute(stmt)).scalars().all())
            rows.reverse()
            return rows
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_message(self, message_id: uuid.UUID) -> Message | None:
        return await self.session.get(Message, message_id)

    async def last_user_message(self, conversation_id: uuid.UUID) -> Message | None:
        return await self.session.scalar(
            select(Message).where(Message.conversation_id == conversation_id, Message.role == "user").order_by(Message.seq.desc()).limit(1)
        )

    async def delete_after(self, conversation_id: uuid.UUID, seq: int) -> None:
        """Delete every message after `seq` (used by regenerate) and keep counters in step."""
        removed = (
            await self.session.execute(
                select(func.count()).select_from(Message).where(
                    Message.conversation_id == conversation_id, Message.seq > seq, Message.role.in_(("user", "assistant"))
                )
            )
        ).scalar_one()
        await self.session.execute(delete(Message).where(Message.conversation_id == conversation_id, Message.seq > seq))
        meta = await self.session.scalar(select(ConversationMetadata).where(ConversationMetadata.conversation_id == conversation_id))
        if meta and removed:
            meta.message_count = max(0, (meta.message_count or 0) - removed)
        await self.session.flush()

    async def tool_logs_for_messages(self, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ToolExecutionLog]]:
        if not message_ids:
            return {}
        rows = (
            await self.session.execute(
                select(ToolExecutionLog).where(ToolExecutionLog.assistant_message_id.in_(message_ids)).order_by(ToolExecutionLog.created_at)
            )
        ).scalars().all()
        out: dict[uuid.UUID, list[ToolExecutionLog]] = {}
        for r in rows:
            out.setdefault(r.assistant_message_id, []).append(r)  # type: ignore[arg-type]
        return out

    async def touch(self, conv: Conversation, when: datetime | None = None) -> None:
        conv.last_message_at = when or utcnow()
        await self.session.flush()
