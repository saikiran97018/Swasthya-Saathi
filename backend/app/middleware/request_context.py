"""Request id + access log. We log method, path, status and timing -- never bodies (they hold user speech/text)."""
from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

log = logging.getLogger("app.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("%s %s -> unhandled error [%s]", request.method, request.url.path, request_id)
            raise
        ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        if request.url.path != "/api/v1/health":
            log.info("%s %s -> %s %.0fms [%s]", request.method, request.url.path, response.status_code, ms, request_id)
        return response
