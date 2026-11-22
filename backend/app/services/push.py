"""Phone / browser notifications (Web Push) for reminders.

A device opts in from Settings (the browser asks permission first) and is stored as a `PushSubscription`. When a reminder is
delivered it is also pushed to every device of that person, so it pops up on the phone even when the app is closed.
Nothing leaves the server except the reminder text, encrypted for that device. Gone devices (HTTP 404/410) are removed.

The VAPID signing key is derived from JWT_SECRET unless VAPID_PRIVATE_KEY is set, so push works with no extra setup.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.database.models import PushSubscription

log = logging.getLogger("app.push")

MAX_DEVICES_PER_USER = 10


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _private_key(settings: Settings) -> ec.EllipticCurvePrivateKey:
    if settings.vapid_private_key:
        raw = base64.urlsafe_b64decode(settings.vapid_private_key + "=" * (-len(settings.vapid_private_key) % 4))
    else:  # deterministic: the same JWT_SECRET always gives the same key, so subscriptions survive restarts and redeploys
        raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"swasthya-saathi-vapid-v1").derive(settings.jwt_secret.encode())
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def vapid_keys(settings: Settings) -> tuple[str, str]:
    """(private scalar, public point) as base64url: the private one goes to pywebpush, the public one to the browser."""
    key = _private_key(settings)
    private = _b64(key.private_numbers().private_value.to_bytes(32, "big"))
    public = _b64(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    return private, public


class PushService:
    def __init__(self, settings: Settings):
        self.s = settings
        self._private, self.public_key = vapid_keys(settings)

    @property
    def available(self) -> bool:
        return self.s.push_enabled

    def _send_blocking(self, sub: PushSubscription, payload: str) -> None:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=payload,
            vapid_private_key=self._private,
            vapid_claims={"sub": self.s.vapid_subject},
            ttl=24 * 3600,  # a reminder that could not be shown for a day is stale
            timeout=10,
        )

    async def send_to_user(self, session: AsyncSession, user_id, *, title: str, body: str, url: str = "/activity", tag: str | None = None) -> int:
        """Push to every device of `user_id`. Returns how many devices accepted it. Never raises."""
        if not self.available:
            return 0
        subs = (await session.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id))).all()
        if not subs:
            return 0
        payload = json.dumps({"title": title[:120], "body": body[:300], "url": url, "tag": tag}, ensure_ascii=False)
        ok, gone = 0, []
        for sub in subs:
            try:
                await asyncio.to_thread(self._send_blocking, sub, payload)
                ok += 1
            except WebPushException as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (404, 410):
                    gone.append(sub.id)  # the person removed the app or revoked permission: forget the device
                else:
                    log.warning("push rejected (HTTP %s)", status)  # never log the endpoint: it is a secret address
            except Exception as exc:
                log.warning("push failed: %s", type(exc).__name__)
        if gone:
            await session.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
        return ok
