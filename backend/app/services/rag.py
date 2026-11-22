"""Retrieval for every turn (RAG): the most relevant verified notes are put in front of the model BEFORE it answers.

Before this, the knowledge base was only a tool the model could choose to call, and it often answered health questions from memory
instead. Now the assistant is always handed the matching notes, plus a short block about this person's own upcoming visits, so
it answers from them and does not lose track of what it already booked.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.database.models import Appointment, User, utcnow
from app.database.repositories.knowledge import KnowledgeRepository, tokenize
from app.services.llm_service import LLMService
from app.services.vaccines import VaccinationService

log = logging.getLogger("app.rag")
_IST = timezone(timedelta(hours=5, minutes=30))
_LATIN = re.compile(r"[A-Za-z]")
_TO_ENGLISH = (
    "Turn the user's message into a short English search query (at most 12 words) about the health topic, scheme or problem it asks about. "
    "Output only the query. If the message is not about health, schemes or first aid, output NONE."
)


def mostly_latin(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return not letters or sum(1 for c in letters if _LATIN.match(c)) / len(letters) > 0.6


class RagService:
    def __init__(self, settings: Settings, llm: LLMService):
        self.s, self.llm = settings, llm

    async def _english_query(self, text: str) -> str | None:
        """The knowledge base is English: turn Hindi, Telugu, Tamil... questions into an English query (one short model call)."""
        if mostly_latin(text):
            return text
        if not self.llm.configured:
            return None
        try:
            out = await asyncio.wait_for(
                self.llm.complete([{"role": "system", "content": _TO_ENGLISH}, {"role": "user", "content": text[:400]}], temperature=0, max_tokens=40),
                timeout=self.s.rag_translate_timeout_seconds,
            )
        except Exception as exc:
            log.info("rag query translation skipped: %s", type(exc).__name__)
            return None
        out = (out or "").strip().strip('"')
        return None if not out or out.upper().startswith("NONE") else out

    async def reference_notes(self, session: AsyncSession, user_texts: list[str], english_query: str | None = None) -> str:
        """Verified notes for the person's latest question ('' when nothing relevant). `user_texts` are their messages, oldest first."""
        if not self.s.rag_enabled or not user_texts:
            return ""
        latest = user_texts[-1]
        query = english_query if english_query is not None else await self._english_query(latest)  # "" = the classifier saw no topic
        if not query:
            return ""
        if len(tokenize(query)) < 3 and len(user_texts) > 1:  # "and for children?" is a follow-up: keep the earlier topic
            earlier = await self._english_query(user_texts[-2])
            query = f"{earlier or ''} {query}".strip()
        hits = await KnowledgeRepository(session).search(query, self.s.rag_top_k + 1, min_score=self.s.rag_min_score)
        if not hits:
            return ""
        hits = [h for h in hits if h.score >= hits[0].score * 0.6][: self.s.rag_top_k]
        body = "\n".join(f"[{i}] {h.title}: {' '.join(h.text.split())[: self.s.rag_chunk_chars]}" for i, h in enumerate(hits, 1))
        return (
            "REFERENCE NOTES (verified; answer from these when the question is about health, schemes or first aid; do not add facts beyond them. "
            "If they do not cover the question, say you do not have verified information and suggest a doctor or the 104 or 112 helpline):\n" + body
        )

    async def person_context(self, session: AsyncSession, user: User) -> str:
        """What this person already has booked, so 'my appointment' and 'cancel it' are understood without guessing."""
        now = utcnow()
        rows = (
            await session.scalars(
                select(Appointment).options(selectinload(Appointment.provider))
                .where(Appointment.user_id == user.id, Appointment.status == "booked", Appointment.starts_at >= now)
                .order_by(Appointment.starts_at).limit(3)
            )
        ).all()
        vaccines = await VaccinationService(session).due_summary(user.id)
        if not rows:
            return vaccines
        lines = []
        for a in rows:
            when = a.starts_at.astimezone(_IST).strftime("%a %d %b, %I:%M %p")
            where = a.provider.name if a.provider else "clinic"
            kind = "" if a.clinic_confirmed else " (planned; clinic has not confirmed)"
            lines.append(f"{a.ref} on {when} IST at {where}{kind}")
        return "Upcoming visits: " + "; ".join(lines) + "." + (f"\n{vaccines}" if vaccines else "")
