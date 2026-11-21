"""Sliding-window rate limiter (per client IP), with a stricter bucket for AI endpoints.

In-memory and per-process, which is right for a single server or a demo. Behind several
workers/instances, put the same logic on Redis (or use your API gateway's limiter).
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_WINDOW = 60.0


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int) -> float | None:
        """Record a hit. Returns None if allowed, else seconds until a slot frees up."""
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > _WINDOW:
            q.popleft()
        if len(q) >= limit:
            return max(0.1, _WINDOW - (now - q[0]))
        q.append(now)
        if len(self._hits) > 10000:  # cheap memory guard
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > _WINDOW][:5000]:
                self._hits.pop(k, None)
        return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, api_prefix: str, general_per_minute: int, ai_per_minute: int, trust_proxy: bool = False):
        super().__init__(app)
        self.window = SlidingWindow()
        self.general, self.ai = general_per_minute, ai_per_minute
        self.trust_proxy = trust_proxy
        self.health = f"{api_prefix}/health"
        self.ai_re = re.compile(rf"^{re.escape(api_prefix)}/(chat|voice/|agents/executions/[^/]+/confirm)")

    def _client(self, request: Request) -> str:
        if self.trust_proxy:
            fwd = request.headers.get("x-forwarded-for")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path == self.health or not path.startswith("/api"):
            return await call_next(request)
        client = self._client(request)
        bucket, limit = ("ai", self.ai) if self.ai_re.match(path) else ("general", self.general)
        retry = self.window.check(f"{client}:{bucket}", limit)
        if retry is not None:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(int(retry) + 1)},
                content={"error": {"code": "rate_limited", "message": "Too many requests. Please slow down and try again shortly.", "details": {"retry_after_seconds": int(retry) + 1}}},
            )
        return await call_next(request)
