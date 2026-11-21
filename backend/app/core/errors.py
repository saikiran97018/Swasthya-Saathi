"""Application errors. Each carries an HTTP status and a stable machine-readable code."""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMedia(AppError):
    status_code = 415
    code = "unsupported_media_type"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class UpstreamError(AppError):
    """A dependency (Bhashini, the LLM API, a webhook) failed."""

    status_code = 502
    code = "upstream_error"

    def __init__(self, message: str, *, retryable: bool = False, **kw: Any):
        super().__init__(message, **kw)
        self.retryable = retryable


class ServiceUnavailable(AppError):
    """A dependency is not configured (missing API key etc.)."""

    status_code = 503
    code = "service_unavailable"
