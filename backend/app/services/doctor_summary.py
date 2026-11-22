"""A short note for the doctor, written from the patient's OWN words in a chat.

The model is told to use only what the patient said, and its note is checked like any reply (no invented numbers, no doses or medicine
names the patient did not say, no diagnosis). If it fails the check or the model is down, a plain note built straight from the
patient's words is used instead, so the person always gets something accurate to show the clinic.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.services.llm_service import LLMService
from app.services.response_validator import validate_response

log = logging.getLogger("app.summary")
IST = timezone(timedelta(hours=5, minutes=30))
MAX_USER_MESSAGES = 12
MAX_CHARS = 400

PROMPT = (
    "Write a short note for a doctor from a patient's own words. Use ONLY facts the patient stated. Use these lines: Who; Main problem; How long; "
    "Other symptoms; Medicines or allergies mentioned; Questions to ask the doctor. Write 'not mentioned' when unknown. No diagnosis, no advice, "
    "no medicine suggestions, no doses unless the patient said them. English, plain text, at most 120 words."
)


def patient_lines(user_messages: list[str]) -> list[str]:
    return [" ".join(m.split())[:MAX_CHARS] for m in user_messages if m and m.strip()][-MAX_USER_MESSAGES:]


def basic_note(user_messages: list[str], memory: dict | None, today: datetime | None = None) -> str:
    memory = memory or {}
    when = (today or datetime.now(IST)).strftime("%d %b %Y")
    said = patient_lines(user_messages)
    lines = [f"Note for the doctor, {when} (the patient's own words)", f"Patient: {memory.get('patient') or 'the person using Swasthya Saathi'}" + (f", age {memory['age']}" if memory.get("age") else "")]
    if memory.get("symptoms"):
        extra = ", ".join(x for x in (memory.get("urgency"), memory.get("specialty")) if x)
        lines.append(f"Main problem: {memory['symptoms']}" + (f" (Saathi's check: {extra})" if extra else ""))
    lines.append("What they said:")
    lines += [f"- {m}" for m in said[-5:]] or ["- (nothing yet)"]
    lines.append("Swasthya Saathi is an information assistant, not a doctor.")
    return "\n".join(lines)


async def write_note(llm: LLMService, user_messages: list[str], memory: dict | None, *, timeout: float = 20) -> tuple[str, str]:
    """(text, source) where source is 'assistant' or 'basic'."""
    said = patient_lines(user_messages)
    fallback = basic_note(said, memory)
    if not said or not llm.configured:
        return fallback, "basic"
    facts = "\n".join(f"- {m}" for m in said)
    ctx = "".join(f"\n{k}: {v}" for k, v in (memory or {}).items() if k in ("patient", "symptoms", "urgency", "age") and v)
    try:
        text = await asyncio.wait_for(llm.complete([{"role": "system", "content": PROMPT}, {"role": "user", "content": f"Patient's messages:\n{facts}{ctx}"}], temperature=0.1, max_tokens=300), timeout=timeout)
    except Exception as exc:
        log.info("doctor note by model skipped: %s", type(exc).__name__)
        return fallback, "basic"
    check = validate_response(text or "", language="en", voice=False, intent="other", grounding="\n".join(said) + ctx)
    if not check.ok or len(check.text) < 30:
        log.info("doctor note by model rejected: %s", check.problems)
        return fallback, "basic"
    return check.text.strip(), "assistant"
