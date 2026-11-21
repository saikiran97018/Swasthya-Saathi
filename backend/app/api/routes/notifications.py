import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.mappers import notification_out
from app.core.errors import NotFound
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import User, utcnow
from app.database.repositories.appointments import ReminderRepository
from app.schemas.misc import NotificationOut, NotificationPage

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> NotificationPage:
    """Delivered reminders (appointment reminders, follow-ups, feedback requests). Poll this for the bell badge."""
    rows, total, unread = await ReminderRepository(session).notifications(user.id, unread_only=unread_only, limit=limit, offset=offset)
    return NotificationPage(items=[notification_out(r) for r in rows], total=total, unread_count=unread)


@router.post("/read-all")
async def mark_all_read(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, int]:
    return {"marked_read": await ReminderRepository(session).mark_all_read(user.id)}


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(notification_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> NotificationOut:
    r = await ReminderRepository(session).get_owned(user.id, notification_id)
    if r is None or r.status != "delivered":
        raise NotFound("Notification not found", code="notification_not_found")
    r.read_at = r.read_at or utcnow()
    await session.flush()
    return notification_out(r)
