"""Outbound integration webhook (HMAC-signed). Lets a real hospital system / SMS gateway react to events."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import Settings

log = logging.getLogger("app.webhooks")


async def send_webhook(http: httpx.AsyncClient | None, settings: Settings, event: str, data: dict[str, Any]) -> dict[str, Any]:
    """POST {event, data, sent_at} to WEBHOOK_URL. Never raises: delivery problems are returned, not thrown."""
    if not settings.webhook_url or http is None:
        return {"ok": False, "configured": False}
    body = json.dumps({"event": event, "data": data, "sent_at": datetime.now(timezone.utc).isoformat()}, default=str)
    headers = {"Content-Type": "application/json", "X-Event": event}
    if settings.webhook_secret:
        headers["X-Signature"] = hmac.new(settings.webhook_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    try:
        r = await http.post(settings.webhook_url, content=body, headers=headers)
        return {"ok": r.status_code < 300, "configured": True, "http_status": r.status_code}
    except httpx.HTTPError as exc:
        log.warning("webhook %s failed: %s", event, type(exc).__name__)
        return {"ok": False, "configured": True, "error": type(exc).__name__}
