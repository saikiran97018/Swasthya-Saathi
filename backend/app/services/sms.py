"""Text-message (SMS) reminders through Twilio's REST API.

Only reminders for people who switched "text me my reminders" on are ever sent, only to the mobile number given for that visit,
and at most once per reminder. A failed text never stops the in-app reminder from being delivered. Keys are never logged.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from app.core.config import Settings

log = logging.getLogger("app.sms")


@dataclass(frozen=True)
class SmsResult:
    ok: bool
    detail: str = ""  # a short, secret-free reason when it failed


def to_e164(mobile: str, country_code: str = "+91") -> str | None:
    """'9876543210' -> '+919876543210'. Accepts an already international number; None when it is not a plausible number."""
    digits = re.sub(r"[^\d+]", "", mobile or "")
    if digits.startswith("+"):
        return digits if re.fullmatch(r"\+\d{8,15}", digits) else None
    digits = digits.lstrip("0")
    if len(digits) == 12 and digits.startswith(country_code.lstrip("+")):
        return "+" + digits
    return f"{country_code}{digits}" if re.fullmatch(r"\d{10}", digits) else None


def shorten(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


class SmsService:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.s, self.http = settings, http

    @property
    def configured(self) -> bool:
        return self.s.sms_configured

    async def send(self, mobile: str, text: str) -> SmsResult:
        if not self.configured:
            return SmsResult(False, "sms_not_configured")
        to = to_e164(mobile, self.s.sms_country_code)
        if to is None:
            return SmsResult(False, "invalid_number")
        body = {"To": to, "Body": shorten(text, self.s.sms_max_chars)}
        body["MessagingServiceSid" if self.s.sms_from.startswith("MG") else "From"] = self.s.sms_from
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.s.twilio_account_sid}/Messages.json"
        try:
            resp = await self.http.post(url, data=body, auth=(self.s.twilio_account_sid, self.s.twilio_auth_token), timeout=15)
        except httpx.HTTPError:
            log.warning("SMS could not reach Twilio")
            return SmsResult(False, "unreachable")
        if resp.status_code in (200, 201):
            return SmsResult(True)
        try:
            err = resp.json()
        except ValueError:
            err = {}
        code = str(err.get("code") or resp.status_code)[:12]
        log.warning("SMS rejected by Twilio: HTTP %s code %s", resp.status_code, code)  # never the request or the credentials
        return SmsResult(False, f"twilio_{code}")
