"""Phone / browser notification sign-up: the web app registers this device here after the person allows notifications."""
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest, Conflict
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import PushSubscription, User
from app.services.push import MAX_DEVICES_PER_USER

router = APIRouter(tags=["push"])


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=160)
    auth: str = Field(min_length=8, max_length=64)


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)
    keys: PushKeys


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)


class PushConfigOut(BaseModel):
    available: bool
    public_key: str
    devices: int = 0  # how many of this person's devices get notifications


async def _count(session: AsyncSession, user: User) -> int:
    return await session.scalar(select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == user.id)) or 0


@router.get("/push/config", response_model=PushConfigOut)
async def push_config(request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> PushConfigOut:
    push = request.app.state.push
    return PushConfigOut(available=push.available, public_key=push.public_key, devices=await _count(session, user))


@router.post("/push/subscriptions", response_model=PushConfigOut, status_code=201)
async def subscribe(body: PushSubscribeIn, request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> PushConfigOut:
    push = request.app.state.push
    if not push.available:
        raise BadRequest("Notifications are not enabled on this server", code="push_unavailable")
    ua = (request.headers.get("user-agent") or "")[:200] or None
    existing = await session.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if existing:  # the same device signing up again (or after a sign-in change): point it at this account
        existing.user_id, existing.p256dh, existing.auth, existing.user_agent = user.id, body.keys.p256dh, body.keys.auth, ua
    else:
        if await _count(session, user) >= MAX_DEVICES_PER_USER:
            raise Conflict(f"You can get notifications on up to {MAX_DEVICES_PER_USER} devices. Turn it off on one first.", code="too_many_devices")
        session.add(PushSubscription(user_id=user.id, endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth, user_agent=ua))
    await session.flush()
    return PushConfigOut(available=True, public_key=push.public_key, devices=await _count(session, user))


@router.delete("/push/subscriptions", status_code=204)
async def unsubscribe(body: PushUnsubscribeIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> Response:
    await session.execute(delete(PushSubscription).where(PushSubscription.user_id == user.id, PushSubscription.endpoint == body.endpoint))
    return Response(status_code=204)


@router.post("/push/test")
async def push_test(request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> dict:
    """Send a test notification to this person's devices, so they can see it works."""
    sent = await request.app.state.push.send_to_user(session, user.id, title="Swasthya Saathi", body="Notifications are on. You will get your visit reminders here.", tag="test")
    return {"sent": sent}
