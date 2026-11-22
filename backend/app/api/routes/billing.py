"""Saathi Plus subscription (Razorpay): plans, status, subscribe, verify, cancel, and the webhook that keeps it all in sync."""
import json
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BadRequest, Conflict, NotFound
from app.api.deps import get_app_settings
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import Subscription, User
from app.services.billing import PLANS, BillingService, apply_entity, current_subscription, is_plus, usage_today

router = APIRouter(tags=["billing"])
log = logging.getLogger("app.billing")

FEATURES = [
    "Unlimited chat with Saathi, every day",
    "Unlimited live voice calls",
    "Priority for new features",
]


class PlanOut(BaseModel):
    id: str
    name: str
    price_inr: int
    period: str
    note: str | None = None


class PlansOut(BaseModel):
    enabled: bool
    key_id: str | None = None  # public: Razorpay Checkout needs it
    plans: list[PlanOut]
    features: list[str]
    free_daily_messages: int
    free_daily_calls: int


class StatusOut(BaseModel):
    plan: Literal["free", "plus"]
    status: str | None = None
    billing_period: str | None = None
    renews_at: datetime | None = None  # when the paid period ends (and renews, unless cancelled)
    cancel_at_cycle_end: bool = False
    messages_today: int
    messages_limit: int | None = None  # None = unlimited
    calls_today: int
    calls_limit: int | None = None


class SubscribeIn(BaseModel):
    plan: Literal["monthly", "yearly"]


class SubscribeOut(BaseModel):
    subscription_id: str
    key_id: str
    plan: str


class VerifyIn(BaseModel):
    razorpay_payment_id: str = Field(min_length=5, max_length=64)
    razorpay_subscription_id: str = Field(min_length=5, max_length=64)
    razorpay_signature: str = Field(min_length=10, max_length=128)


def _svc(request: Request) -> BillingService:
    return request.app.state.billing


async def _status(session: AsyncSession, settings: Settings, user: User) -> StatusOut:
    sub = await current_subscription(session, user.id)
    plus = is_plus(sub)
    used = await usage_today(session, user.id)
    return StatusOut(
        plan="plus" if plus else "free", status=sub.status if sub else None, billing_period=sub.plan if sub else None,
        renews_at=sub.current_end if plus and sub else None, cancel_at_cycle_end=bool(sub and plus and (sub.cancel_at_cycle_end or sub.status == "cancelled")),
        messages_today=used.messages_today, calls_today=used.calls_today,
        messages_limit=None if plus or not settings.billing_enabled or settings.free_daily_messages <= 0 else settings.free_daily_messages,
        calls_limit=None if plus or not settings.billing_enabled or settings.free_daily_calls <= 0 else settings.free_daily_calls,
    )


@router.get("/billing/plans", response_model=PlansOut)
async def plans(settings: Settings = Depends(get_app_settings), user: User = Depends(get_current_user)) -> PlansOut:
    out = [PlanOut(id="monthly", name="Saathi Plus, monthly", price_inr=settings.plan_monthly_inr, period="month")]
    if settings.razorpay_plan_yearly:
        saving = settings.plan_monthly_inr * 12 - settings.plan_yearly_inr
        out.append(PlanOut(id="yearly", name="Saathi Plus, yearly", price_inr=settings.plan_yearly_inr, period="year", note=f"Save ₹{saving}" if saving > 0 else None))
    return PlansOut(
        enabled=settings.billing_enabled, key_id=settings.razorpay_key_id if settings.billing_enabled else None, plans=out if settings.billing_enabled else [],
        features=FEATURES, free_daily_messages=settings.free_daily_messages, free_daily_calls=settings.free_daily_calls,
    )


@router.get("/billing/status", response_model=StatusOut)
async def status(settings: Settings = Depends(get_app_settings), user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> StatusOut:
    return await _status(session, settings, user)


@router.post("/billing/subscribe", response_model=SubscribeOut, status_code=201)
async def subscribe(body: SubscribeIn, request: Request, settings: Settings = Depends(get_app_settings), user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> SubscribeOut:
    if body.plan not in PLANS:
        raise BadRequest("Unknown plan", code="unknown_plan")
    if is_plus(await current_subscription(session, user.id)):
        raise Conflict("You already have Saathi Plus.", code="already_subscribed")
    created = await _svc(request).create_subscription(user, body.plan)
    session.add(Subscription(user_id=user.id, plan=body.plan, razorpay_subscription_id=created["id"], status=str(created.get("status", "created"))[:16]))
    await session.flush()
    return SubscribeOut(subscription_id=created["id"], key_id=settings.razorpay_key_id, plan=body.plan)


@router.post("/billing/verify", response_model=StatusOut)
async def verify(body: VerifyIn, request: Request, settings: Settings = Depends(get_app_settings), user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> StatusOut:
    """Checkout finished in the browser: check Razorpay's signature, then ask Razorpay for the real state (the webhook confirms it later)."""
    svc = _svc(request)
    if not svc.verify_checkout(body.razorpay_payment_id, body.razorpay_subscription_id, body.razorpay_signature):
        raise BadRequest("The payment could not be verified.", code="bad_signature")
    sub = await session.scalar(select(Subscription).where(Subscription.razorpay_subscription_id == body.razorpay_subscription_id, Subscription.user_id == user.id))
    if sub is None:
        raise NotFound("No such subscription", code="subscription_not_found")
    sub.last_payment_id = body.razorpay_payment_id
    try:
        apply_entity(sub, await svc.fetch(sub.razorpay_subscription_id))
    except Exception:  # the signature already proved the payment; the webhook will fill in the rest
        log.warning("could not refresh the subscription after checkout; waiting for the webhook")
        sub.status = "active" if sub.status in {"created", "authenticated"} else sub.status
        sub.paid_count = max(sub.paid_count, 1)
    await session.flush()
    return await _status(session, settings, user)


@router.post("/billing/cancel", response_model=StatusOut)
async def cancel(request: Request, settings: Settings = Depends(get_app_settings), user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> StatusOut:
    """Stop renewing. Plus keeps working until the end of the period that is already paid for."""
    sub = await current_subscription(session, user.id)
    if sub is None or not is_plus(sub) or sub.status != "active":
        raise BadRequest("There is no active subscription to cancel.", code="nothing_to_cancel")
    await _svc(request).cancel(sub.razorpay_subscription_id)
    sub.cancel_at_cycle_end = True
    await session.flush()
    return await _status(session, settings, user)


@router.post("/billing/webhook", include_in_schema=False)
async def webhook(request: Request, session: AsyncSession = Depends(get_session, scope="function")) -> dict:
    """Razorpay calls this (signed) when a payment succeeds, renews, fails or the subscription is cancelled."""
    raw = await request.body()
    if not _svc(request).verify_webhook(raw, request.headers.get("x-razorpay-signature", "")):
        raise BadRequest("Bad signature", code="bad_signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise BadRequest("Not JSON", code="invalid_payload")
    result = await _svc(request).handle_event(session, request.headers.get("x-razorpay-event-id"), payload if isinstance(payload, dict) else {})
    log.info("billing webhook %s: %s", payload.get("event") if isinstance(payload, dict) else "?", result)
    return {"status": result}
