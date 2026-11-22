"""Thumbs up / down on an assistant reply. A thumbs-down with a reason is how wrong or unsafe answers are found and fixed."""
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import Conversation, Message, MessageFeedback, User

router = APIRouter(tags=["feedback"])

Reason = Literal["wrong_info", "unsafe", "misunderstood", "not_helpful", "other"]


class ReplyFeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    reason: Reason | None = None
    note: str | None = Field(default=None, max_length=500)


class ReplyFeedbackOut(BaseModel):
    message_id: str
    rating: Literal["up", "down"]
    reason: Reason | None = None


async def _own_reply(session: AsyncSession, user: User, message_id) -> Message:
    msg = await session.scalar(
        select(Message).join(Conversation, Message.conversation_id == Conversation.id)
        .where(Message.id == message_id, Conversation.user_id == user.id, Message.role == "assistant")
    )
    if msg is None:
        raise NotFound("No such reply", code="message_not_found")
    return msg


@router.put("/messages/{message_id}/feedback", response_model=ReplyFeedbackOut)
async def rate_reply(message_id: str, body: ReplyFeedbackIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> ReplyFeedbackOut:
    import uuid

    try:
        mid = uuid.UUID(message_id)
    except ValueError:
        raise NotFound("No such reply", code="message_not_found") from None
    msg = await _own_reply(session, user, mid)
    row = await session.scalar(select(MessageFeedback).where(MessageFeedback.message_id == msg.id, MessageFeedback.user_id == user.id))
    reason = body.reason if body.rating == "down" else None
    note = " ".join((body.note or "").split())[:500] or None if body.rating == "down" else None
    if row is None:
        session.add(MessageFeedback(user_id=user.id, message_id=msg.id, rating=body.rating, reason=reason, note=note))
    else:
        row.rating, row.reason, row.note = body.rating, reason, note
    await session.flush()
    return ReplyFeedbackOut(message_id=str(msg.id), rating=body.rating, reason=reason)


@router.delete("/messages/{message_id}/feedback", status_code=204)
async def clear_feedback(message_id: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> Response:
    import uuid

    try:
        mid = uuid.UUID(message_id)
    except ValueError:
        return Response(status_code=204)
    row = await session.scalar(select(MessageFeedback).where(MessageFeedback.message_id == mid, MessageFeedback.user_id == user.id))
    if row is not None:
        await session.delete(row)
    return Response(status_code=204)
