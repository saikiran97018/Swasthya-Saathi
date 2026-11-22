"""Application service for a chat turn: conversations, language, persistence, errors, titles, memory.

Every public method is an async generator of *events* (plain dicts) so the same logic serves
the WebSocket (events streamed live) and the REST endpoints (events collected into one reply).

Event types: conversation, language, user_message, stage, token, message, tool_start,
tool_result, confirmation_required, error, done.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import AgentOrchestrator, TurnState, message_event, tool_event
from app.agents.prompts import SUMMARY_PROMPT, TITLE_PROMPT
from app.core.config import Settings
from app.core.errors import AppError, BadRequest, NotFound
from app.database.models import AgentExecution, Conversation, User, utcnow
from app.database.repositories.conversations import ConversationRepository
from app.database.repositories.executions import ExecutionRepository
from app.database.repositories.users import UserRepository
from app.schemas.conversation import ConversationOut, MessageOut
from app.services.billing import check_message_allowed
from app.utils.transcript import check_transcript
from app.services.llm_service import LLMService
from app.utils.language import detect_script_language, normalise_language, same_script_family

log = logging.getLogger("app.agent_service")

Event = dict[str, Any]


class AgentService:
    def __init__(self, settings: Settings, llm: LLMService, orchestrator: AgentOrchestrator):
        self.s = settings
        self.llm = llm
        self.orch = orchestrator

    # ================================================================== public entry points
    async def handle_message(
        self,
        session: AsyncSession,
        user: User,
        *,
        conversation_id: uuid.UUID | None,
        text: str,
        input_mode: str = "text",
        language: str | None = None,
        voice_output: bool = False,
    ) -> AsyncIterator[Event]:
        text = (text or "").strip()
        if text and input_mode == "voice":  # never act on text a recogniser invented from noise
            heard = check_transcript(text)
            if not heard.ok:
                raise BadRequest("I could not make that out. Please say it again.", code="unclear_speech")
            text = heard.text
        if not text:
            raise BadRequest("Message is empty")
        if len(text) > self.s.max_message_chars:
            raise BadRequest(f"Message is longer than {self.s.max_message_chars} characters")

        await check_message_allowed(session, self.s, user)  # free plan: a daily limit (no-op until Razorpay is set up)

        repo = ConversationRepository(session)
        prefs = await UserRepository(session).get_preferences(user.id)

        if conversation_id:
            conv = await repo.get_owned(conversation_id, user.id)
        else:
            start_lang = normalise_language(language, await UserRepository(session).primary_language(user.id))
            conv = await repo.create(user.id, title=_clip_title(text), language=start_lang)

        # ---- decide the language of this turn (explicit choice > script detection > keep) ----
        previous = conv.language
        if language:
            conv.language = normalise_language(language, conv.language)
        elif prefs.auto_detect_language:
            detected = detect_script_language(text)
            if detected and not same_script_family(detected, conv.language):
                conv.language = detected
        yield {"type": "conversation", "conversation": await self._conversation_out(repo, conv)}
        yield {"type": "language", "language": conv.language, "changed": conv.language != previous}

        state = await self._prepare_state(session, user, conv, input_mode=input_mode, voice=voice_output or input_mode == "voice")
        await self.orch.cancel_pending(state, await ExecutionRepository(session).pending_logs(conv.id))

        user_msg = await repo.add_message(conv, role="user", content=text, language=conv.language, input_mode=input_mode)
        state.execution.user_message_id = user_msg.id
        await session.commit()
        yield {"type": "user_message", "message": MessageOut.from_model(user_msg).model_dump(mode="json")}

        async for ev in self._run(state, repo):
            yield ev

    async def regenerate(self, session: AsyncSession, user: User, *, conversation_id: uuid.UUID, voice_output: bool = False) -> AsyncIterator[Event]:
        repo = ConversationRepository(session)
        conv = await repo.get_owned(conversation_id, user.id)
        last_user = await repo.last_user_message(conv.id)
        if last_user is None:
            raise BadRequest("There is nothing to regenerate yet")

        state = await self._prepare_state(session, user, conv, input_mode=last_user.input_mode, voice=voice_output or last_user.input_mode == "voice")
        await self.orch.cancel_pending(state, await ExecutionRepository(session).pending_logs(conv.id))
        await repo.delete_after(conv.id, last_user.seq)
        state.execution.user_message_id = last_user.id
        await session.commit()
        yield {"type": "conversation", "conversation": await self._conversation_out(repo, conv)}
        yield {"type": "language", "language": conv.language, "changed": False}
        async for ev in self._run(state, repo):
            yield ev

    async def confirm(self, session: AsyncSession, user: User, *, tool_execution_id: uuid.UUID, approve: bool, voice_output: bool = False) -> AsyncIterator[Event]:
        exec_repo = ExecutionRepository(session)
        entry = await exec_repo.get_tool_log(tool_execution_id, user.id)
        if entry is None:
            raise NotFound("Tool execution not found", code="tool_execution_not_found")
        if entry.status != "awaiting_confirmation":
            raise BadRequest("This action is no longer waiting for confirmation", code="not_awaiting_confirmation")

        repo = ConversationRepository(session)
        conv = await repo.get_owned(entry.conversation_id, user.id)
        execution = await exec_repo.get_execution(entry.execution_id)
        if execution is None:
            raise NotFound("Execution not found")
        execution.status = "running"

        last_user = await repo.last_user_message(conv.id)
        mode = last_user.input_mode if last_user else "text"
        state = TurnState(session=session, user=user, conversation=conv, execution=execution, language=conv.language,
                          voice=voice_output or mode == "voice", input_mode=mode)
        yield {"type": "conversation", "conversation": await self._conversation_out(repo, conv)}
        yield {"type": "language", "language": conv.language, "changed": False}
        async for ev in self.orch.resolve_confirmation(state, entry, approve):
            yield ev
        await session.commit()
        async for ev in self._run(state, repo):
            yield ev

    # ================================================================== internals
    async def _prepare_state(self, session: AsyncSession, user: User, conv: Conversation, *, input_mode: str, voice: bool) -> TurnState:
        execution = await ExecutionRepository(session).start(conversation_id=conv.id, user_id=user.id, user_message_id=None, model=self.llm.model)
        return TurnState(session=session, user=user, conversation=conv, execution=execution, language=conv.language, voice=voice, input_mode=input_mode)

    async def _run(self, state: TurnState, repo: ConversationRepository) -> AsyncIterator[Event]:
        """Run the orchestrator with uniform error handling, then finalise the execution record."""
        session, ex = state.session, state.execution
        started = utcnow()
        try:
            async for ev in self.orch.run(state):
                yield ev
        except asyncio.CancelledError:
            ex.status, ex.finished_at = "cancelled", utcnow()
            await session.commit()
            raise
        except AppError as exc:
            await self._fail(state, exc.message, exc.code, getattr(exc, "retryable", False))
            yield {"type": "error", "code": exc.code, "message": exc.message, "retryable": getattr(exc, "retryable", False)}
            return
        except Exception:
            log.exception("agent turn crashed")
            await self._fail(state, "Unexpected error", "internal_error", True)
            yield {"type": "error", "code": "internal_error", "message": "Something went wrong. Please try again.", "retryable": True}
            return

        ex.finished_at = utcnow()
        ex.latency_ms = (ex.latency_ms or 0) + int((ex.finished_at - started).total_seconds() * 1000)
        if state.awaiting_confirmation:
            ex.status = "awaiting_confirmation"
        else:
            ex.status = "completed"
            ex.intent = ex.intent or "conversation"
        # keep the conversation's language in step with any set_language tool call
        state.conversation.language = state.language
        await session.commit()

        if not state.awaiting_confirmation:
            await self._maybe_title(state, repo)
            await self._maybe_summarise(state, repo)
            await session.commit()
            yield {"type": "conversation", "conversation": await self._conversation_out(repo, state.conversation)}
        yield {"type": "done", "execution_id": str(ex.id), "status": ex.status, "language": state.language}

    async def _fail(self, state: TurnState, message: str, code: str, retryable: bool) -> None:
        ex = state.execution
        ex.status, ex.error, ex.finished_at = "failed", f"{code}: {message}"[:500], utcnow()
        ex.latency_ms = int((ex.finished_at - ex.started_at).total_seconds() * 1000)
        try:
            await state.session.commit()
        except Exception:  # pragma: no cover
            await state.session.rollback()

    async def _conversation_out(self, repo: ConversationRepository, conv: Conversation) -> dict[str, Any]:
        meta = await repo.get_meta(conv)
        return ConversationOut.from_model(conv, meta).model_dump(mode="json")

    # ---- auto title ---------------------------------------------------------------------------
    async def _maybe_title(self, state: TurnState, repo: ConversationRepository) -> None:
        conv = state.conversation
        meta = await repo.get_meta(conv)
        if not conv.title_is_auto or (meta.message_count or 0) > 4:
            return
        msgs = [m for m in await repo.list_messages(conv.id, limit=6) if m.role in ("user", "assistant") and m.content]
        if not msgs:
            return
        transcript = "\n".join(f"{m.role}: {m.content[:300]}" for m in msgs[:2])
        try:
            title = await asyncio.wait_for(
                self.llm.complete([{"role": "system", "content": TITLE_PROMPT}, {"role": "user", "content": transcript}], temperature=0.2, max_tokens=24),
                timeout=10,
            )
        except Exception as exc:
            log.info("title generation skipped: %s", type(exc).__name__)
            return
        title = title.strip().strip("\"'“”‘’.").splitlines()[0][:80] if title.strip() else ""
        if title:
            conv.title = title
            conv.title_is_auto = (meta.message_count or 0) <= 2  # keep refining until the 2nd exchange

    # ---- rolling memory -----------------------------------------------------------------------
    async def _maybe_summarise(self, state: TurnState, repo: ConversationRepository) -> None:
        conv = state.conversation
        meta = await repo.get_meta(conv)
        fresh = await repo.list_messages(conv.id, after_seq=meta.summarized_until_seq or 0)
        if len(fresh) < self.s.summary_trigger_messages:
            return
        to_summarise = fresh[:-10]  # keep the latest 10 verbatim
        lines = [f"{m.role}: {m.content[:500]}" for m in to_summarise if m.role in ("user", "assistant") and m.content]
        if not lines:
            return
        prior = f"Previous summary:\n{meta.summary}\n\n" if meta.summary else ""
        try:
            summary = await asyncio.wait_for(
                self.llm.complete(
                    [{"role": "system", "content": SUMMARY_PROMPT}, {"role": "user", "content": prior + "New messages:\n" + "\n".join(lines)}],
                    temperature=0.2, max_tokens=300,
                ),
                timeout=20,
            )
        except Exception as exc:
            log.info("summary skipped: %s", type(exc).__name__)
            return
        if summary:
            meta.summary = summary[:1500]
            meta.summarized_until_seq = to_summarise[-1].seq


def _clip_title(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line[:60] + ("…" if len(one_line) > 60 else "")
