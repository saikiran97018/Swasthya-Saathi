"""Standard browser security headers on every HTTP response (pure ASGI, so streaming replies are untouched)."""
from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_BASE = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    # The app needs the microphone (voice) and location (nearby clinics); payment is Razorpay's pop-up.
    (b"permissions-policy", b"microphone=(self), geolocation=(self), camera=(), payment=(self)"),
]
_HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        secure = scope.get("scheme") == "https" or headers.get(b"x-forwarded-proto", b"").split(b",")[0].strip() == b"https"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [h for h in _BASE if h[0] not in existing]
                if secure and _HSTS[0] not in existing:
                    extra.append(_HSTS)
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        await self.app(scope, receive, send_with_headers)
