"""Saathi Plus: a paid plan billed through Razorpay Subscriptions, and the free plan's daily limits.

Flow: the app asks us for a subscription (we create it at Razorpay for the chosen plan) -> Razorpay Checkout collects the first
payment in the browser -> we check Razorpay's signature on the result -> the webhook keeps the status right from then on
(renewals, failed payments, cancellation). Card and UPI details only ever go to Razorpay, never to this server.

The free plan is limited per day (messages, live calls). SOS, emergency numbers and reminders are never limited.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ServiceUnavailable, UpstreamError
from app.database.models import BillingEvent, Conversation, Message, Subscription, User, utcnow

log = logging.getLogger("app.billing")
API = "https://api.razorpay.com/v1"
_IST = timezone(timedelta(hours=5, minutes=30))
PLANS = ("monthly", "yearly")
TOTAL_COUNT = {"monthly": 120, "yearly": 10}  # billing cycles Razorpay will run before the subscription ends (10 years)
LIVE_STATUSES = {"active"}


class PlanLimitReached(AppError):
    status_code = 402
    code = "plan_limit"


@dataclass
class Usage:
    messages_today: int
    calls_today: int


def day_start_utc(now: datetime | None = None) -> datetime:
    local = (now or utcnow()).astimezone(_IST)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def is_plus(sub: Subscription | None, now: datetime | None = None) -> bool:
    """Paid access: an active subscription, or a cancelled one whose paid period has not ended yet."""
    if sub is None:
        return False
    if sub.status in LIVE_STATUSES:
        return True
    return sub.status in {"cancelled", "pending", "halted"} and sub.current_end is not None and sub.current_end > (now or utcnow()) and sub.paid_count > 0


async def current_subscription(session: AsyncSession, user_id) -> Subscription | None:
    rows = (await session.scalars(select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.created_at.desc()))).all()
    paid = [r for r in rows if is_plus(r)]
    return paid[0] if paid else (rows[0] if rows else None)


async def usage_today(session: AsyncSession, user_id) -> Usage:
    since = day_start_utc()
    messages = await session.scalar(
        select(func.count()).select_from(Message).join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id, Message.role == "user", Message.created_at >= since)
    )
    calls = await session.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id, Conversation.title == "Live call", Conversation.created_at >= since)
    )
    return Usage(messages or 0, calls or 0)


_LIMIT_TAIL = " If this is an emergency call 112 now; the SOS screen always works."


async def check_message_allowed(session: AsyncSession, settings: Settings, user: User) -> None:
    """Raise PlanLimitReached when the free plan's daily message limit is used up. No-op until billing is set up."""
    if not settings.billing_enabled or settings.free_daily_messages <= 0:
        return
    if is_plus(await current_subscription(session, user.id)):
        return
    if (await usage_today(session, user.id)).messages_today >= settings.free_daily_messages:
        raise PlanLimitReached(f"You have used your {settings.free_daily_messages} free messages for today. Saathi Plus removes the daily limit.{_LIMIT_TAIL}", code="plan_limit")


async def check_call_allowed(session: AsyncSession, settings: Settings, user: User) -> None:
    if not settings.billing_enabled or settings.free_daily_calls <= 0:
        return
    if is_plus(await current_subscription(session, user.id)):
        return
    if (await usage_today(session, user.id)).calls_today >= settings.free_daily_calls:
        raise PlanLimitReached(f"You have used your {settings.free_daily_calls} free live calls for today. Saathi Plus removes the daily limit.{_LIMIT_TAIL}", code="plan_limit")


def _epoch(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc) if value else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def apply_entity(sub: Subscription, entity: dict[str, Any]) -> None:
    """Copy what Razorpay says about a subscription onto our row."""
    if entity.get("status"):
        sub.status = str(entity["status"])[:16]
    end = _epoch(entity.get("current_end")) or _epoch(entity.get("charge_at"))
    if end:
        sub.current_end = end
    if "paid_count" in entity:
        sub.paid_count = int(entity.get("paid_count") or 0)
    if "has_scheduled_changes" in entity and entity.get("status") == "active":
        sub.cancel_at_cycle_end = bool(entity.get("has_scheduled_changes"))


class BillingService:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.s, self.http = settings, http

    @property
    def enabled(self) -> bool:
        return self.s.billing_enabled

    def plan_id(self, plan: str) -> str:
        pid = self.s.razorpay_plan_monthly if plan == "monthly" else self.s.razorpay_plan_yearly
        if not pid:
            raise ServiceUnavailable(f"The {plan} plan is not set up yet", code="plan_unavailable")
        return pid

    async def _call(self, method: str, path: str, json: dict | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise ServiceUnavailable("Payments are not set up on this server", code="billing_unavailable")
        try:
            resp = await self.http.request(method, f"{API}{path}", json=json, auth=(self.s.razorpay_key_id, self.s.razorpay_key_secret), timeout=20)
        except httpx.HTTPError as exc:
            log.warning("Razorpay unreachable: %s", type(exc).__name__)
            raise UpstreamError("Could not reach the payment service. Please try again.", retryable=True) from exc
        if resp.status_code >= 400:
            try:
                err = (resp.json().get("error") or {}).get("description", "")
            except ValueError:
                err = ""
            log.warning("Razorpay %s %s -> HTTP %s %s", method, path.split("/")[1] if "/" in path else path, resp.status_code, err[:120])
            raise UpstreamError("The payment service could not complete that. Please try again.", retryable=resp.status_code >= 500)
        return resp.json()

    async def create_subscription(self, user: User, plan: str) -> dict[str, Any]:
        return await self._call("POST", "/subscriptions", {
            "plan_id": self.plan_id(plan), "total_count": TOTAL_COUNT[plan], "quantity": 1, "customer_notify": 1,
            "notes": {"user_id": str(user.id), "plan": plan},
        })

    async def fetch(self, subscription_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/subscriptions/{subscription_id}")

    async def cancel(self, subscription_id: str) -> dict[str, Any]:
        return await self._call("POST", f"/subscriptions/{subscription_id}/cancel", {"cancel_at_cycle_end": 1})

    # ---- signatures: both are HMAC-SHA256, compared in constant time ----
    def verify_checkout(self, payment_id: str, subscription_id: str, signature: str) -> bool:
        expected = hmac.new(self.s.razorpay_key_secret.encode(), f"{payment_id}|{subscription_id}".encode(), hashlib.sha256).hexdigest()
        return bool(self.s.razorpay_key_secret) and hmac.compare_digest(expected, signature or "")

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        if not self.s.razorpay_webhook_secret:
            return False
        expected = hmac.new(self.s.razorpay_webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    async def handle_event(self, session: AsyncSession, event_id: str | None, payload: dict[str, Any]) -> str:
        """Apply one webhook event. Returns 'applied', 'duplicate' or 'ignored'."""
        if event_id:
            if await session.scalar(select(BillingEvent.id).where(BillingEvent.event_id == event_id)):
                return "duplicate"
            session.add(BillingEvent(event_id=event_id[:80], event_type=str(payload.get("event", ""))[:48]))
        body = payload.get("payload") or {}
        entity = (body.get("subscription") or {}).get("entity") or {}
        sub_id = entity.get("id")
        if not sub_id:
            return "ignored"
        sub = await session.scalar(select(Subscription).where(Subscription.razorpay_subscription_id == sub_id))
        if sub is None:
            return "ignored"  # not one of ours (or created elsewhere)
        apply_entity(sub, entity)
        pay = (body.get("payment") or {}).get("entity") or {}
        if pay.get("id") and payload.get("event") == "subscription.charged":
            sub.last_payment_id = str(pay["id"])[:64]
        return "applied"
