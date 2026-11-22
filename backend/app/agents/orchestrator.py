"""The agent loop: LLM <-> tools, with persistence, streaming events and confirmation gating.

Flow of one turn
----------------
1. Build the prompt (system prompt + recent history + running summary).
2. Stream the model's answer. If it asks for tools, validate each call, run it (or pause for
   the user's confirmation if the tool is sensitive), store the result, and go back to 1.
3. When the model answers without asking for tools, store the final message and stop.

The loop is a plain `for` loop with a hard step limit rather than a graph framework: it has a
single decision point ("did the model request tools?"), so LangGraph would add dependencies
without adding clarity. The pieces here (tools, history builder, events) map 1:1 onto graph
nodes if you ever want to move to LangGraph.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import build_system_prompt
from app.services import working_memory
from app.utils.language import language_name
from app.services.response_validator import REWRITE_NOTE, fallback_text, validate_response
from app.services.intent import IntentService
from app.services.rag import RagService
from app.agents.tools import ToolContext, ToolError, ToolRegistry
from app.database.repositories.family import FamilyRepository
from app.services.places import PlacesService
from app.core.config import Settings
from app.database.models import AgentExecution, Conversation, ConversationMetadata, ToolExecutionLog, User, utcnow
from app.database.repositories.conversations import ConversationRepository
from app.database.repositories.executions import ExecutionRepository
from app.schemas.conversation import MessageOut, ToolExecutionOut
from app.services.llm_service import LLMService

log = logging.getLogger("app.agent")

FALLBACK_REPLY = "Sorry, I could not come up with an answer. Please try asking again."
MAX_TOOL_CALLS_PER_STEP = 4


@dataclass
class TurnState:
    session: AsyncSession
    user: User
    conversation: Conversation
    execution: AgentExecution
    language: str
    voice: bool
    input_mode: str = "text"
    tools_used: list[str] = field(default_factory=list)
    awaiting_confirmation: bool = False
    intent: str = ""
    context: str = ""  # reference notes + the person's upcoming visits, worked out once per turn


def message_event(msg, logs: list[ToolExecutionLog] | None = None) -> dict[str, Any]:
    return {"type": "message", "message": MessageOut.from_model(msg, logs).model_dump(mode="json")}


def tool_event(kind: str, entry: ToolExecutionLog) -> dict[str, Any]:
    return {"type": kind, "tool_execution": ToolExecutionOut.model_validate(entry).model_dump(mode="json")}


class AgentOrchestrator:
    def __init__(self, llm: LLMService, registry: ToolRegistry, settings: Settings, http: httpx.AsyncClient, places: PlacesService | None = None, rag: RagService | None = None):
        self.llm = llm
        self.rag = rag or RagService(settings, llm)
        self.intents = IntentService(settings, llm)
        self.registry = registry
        self.s = settings
        self.http = http
        self.places = places or PlacesService(settings, http)

    # ---------------------------------------------------------------- history -> LLM messages
    async def _history(self, state: TurnState) -> list[dict[str, Any]]:
        repo = ConversationRepository(state.session)
        meta = await repo.get_meta(state.conversation)
        rows = await repo.list_messages(state.conversation.id, after_seq=meta.summarized_until_seq or 0, limit=self.s.history_message_limit)
        while rows and rows[0].role != "user":  # never start mid tool-exchange
            rows.pop(0)
        out: list[dict[str, Any]] = []
        for m in rows:
            if m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": m.content or None}
                if m.tool_calls:
                    entry["tool_calls"] = m.tool_calls
                    if not m.content:
                        entry["content"] = None
                out.append(entry)
            elif m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        return out

    async def _system_prompt(self, state: TurnState) -> str:
        meta = await ConversationRepository(state.session).get_meta(state.conversation)
        family = [f"{m.name} ({m.relation})" for m in await FamilyRepository(state.session).list(state.user.id)]
        return build_system_prompt(language=state.language, summary=meta.summary, voice=state.voice, display_name=state.user.display_name, family=family, context=state.context)

    async def _turn_context(self, state: TurnState) -> str:
        """Retrieval step: verified notes for this question and what the person already has booked. Never blocks the answer."""
        try:
            users = [m["content"] for m in await self._history(state) if m["role"] == "user" and m.get("content")]
            intent = await self.intents.classify(users[-1]) if users else None
            state.intent = intent.label if intent else ""
            repo = ConversationRepository(state.session)
            meta = await repo.get_meta(state.conversation)
            remembered = working_memory.render((meta.extra or {}).get(working_memory.KEY), await self._earlier_city(state))
            notes = ""
            if intent is None or intent.wants_notes:
                notes = await self.rag.reference_notes(state.session, users, english_query=intent.query if intent and intent.source == "llm" else None)
            parts = [
                intent.hint if intent and intent.emergency else "",  # an emergency instruction always comes first
                await self.rag.person_context(state.session, state.user),
                remembered,
                notes,
                intent.hint if intent and not intent.emergency else "",
                # last, so it wins over a long history in another language: the person's CURRENT language decides the reply language
                f"Reply in {language_name(state.language)} in its native script, even if earlier messages used another language.",
            ]
            return "\n\n".join(p for p in parts if p)
        except Exception as exc:  # retrieval is an extra: the assistant still works (and can call search_knowledge_base) without it
            log.warning("turn context skipped: %s", type(exc).__name__)
            return ""

    async def _check_reply(self, state: TurnState, messages: list[dict[str, Any]], text: str) -> tuple[str, dict[str, Any] | None]:
        """Response validation: repair what can be repaired, ask the model for ONE rewrite on a real problem, else use a safe fallback."""
        if not self.s.response_validation_enabled:
            return text, None
        grounding = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") in ("system", "tool", "user"))
        lang = state.language

        def run(candidate: str):
            return validate_response(candidate, language=lang, voice=state.voice, intent=state.intent, grounding=grounding)

        verdict = run(text)
        record: dict[str, Any] = {}
        if verdict.repairs:
            record["repairs"] = verdict.repairs
        if verdict.ok:
            return verdict.text, record or None
        record["problems"] = verdict.problems
        if self.s.response_validation_retry:
            try:
                note = REWRITE_NOTE.format(problems=", ".join(verdict.problems), lang=language_name(lang))
                again = await asyncio.wait_for(self.llm.complete([*messages, {"role": "system", "content": note}], temperature=0.2, max_tokens=400), timeout=20)
                second = run(again or "")
                if second.ok:
                    record["action"] = "rewritten"
                    record["repairs"] = sorted(set(record.get("repairs", [])) | set(second.repairs))
                    return second.text, record
            except Exception as exc:
                log.info("reply rewrite skipped: %s", type(exc).__name__)
        record["action"] = "fallback"
        log.warning("reply replaced by the safe fallback: %s", ",".join(verdict.problems))
        return fallback_text(lang, state.intent), record

    async def _earlier_city(self, state: TurnState) -> str | None:
        """The city this person searched in during an earlier chat, offered as a default (to be confirmed)."""
        if (await ConversationRepository(state.session).get_meta(state.conversation)).extra.get(working_memory.KEY, {}).get("city"):
            return None  # this chat already has one
        rows = await state.session.execute(
            select(ConversationMetadata.extra).join(Conversation, ConversationMetadata.conversation_id == Conversation.id)
            .where(Conversation.user_id == state.user.id, Conversation.id != state.conversation.id).order_by(Conversation.last_message_at.desc()).limit(5)
        )
        for (extra,) in rows.all():
            city = ((extra or {}).get(working_memory.KEY) or {}).get("city")
            if city:
                return city
        return None

    async def _remember(self, state: TurnState, tool: str, args: dict[str, Any], data: dict[str, Any]) -> None:
        """Fold a successful tool result into the conversation's working memory (no model call)."""
        meta = await ConversationRepository(state.session).get_meta(state.conversation)
        extra = dict(meta.extra or {})
        extra[working_memory.KEY] = working_memory.update(extra.get(working_memory.KEY), tool, args, data)
        meta.extra = extra  # a new dict, so the JSON column is saved

    def _tool_ctx(self, state: TurnState) -> ToolContext:
        return ToolContext(session=state.session, user=state.user, conversation=state.conversation, settings=self.s, http=self.http, places=self.places)

    # ---------------------------------------------------------------- the loop
    async def run(self, state: TurnState) -> AsyncIterator[dict[str, Any]]:
        repo = ConversationRepository(state.session)
        tools_spec = self.registry.specs(self.s)
        state.context = await self._turn_context(state)

        for _ in range(self.s.agent_max_steps):
            state.execution.steps += 1
            yield {"type": "stage", "stage": "thinking"}
            messages = [{"role": "system", "content": await self._system_prompt(state)}, *await self._history(state)]
            # Never hold a database transaction (and its connection / locks) open while waiting on the slow LLM call.
            await state.session.commit()

            text_parts: list[str] = []
            calls = []
            usage = None
            used_model = self.llm.model
            # Spoken replies are held back until they pass the response check (nothing invented may reach the speaker);
            # typed replies stream live and the final message carries the checked text.
            hold = state.voice and self.s.response_validation_enabled
            async for chunk in self.llm.stream_chat(messages, tools_spec):
                if chunk.content:
                    text_parts.append(chunk.content)
                    if not hold:
                        yield {"type": "token", "delta": chunk.content}
                if chunk.finished:
                    calls, usage = chunk.tool_calls, chunk.usage
                    used_model = chunk.model or used_model  # may be the fallback model after a failover
            state.execution.model = used_model
            text = "".join(text_parts).strip()

            # ---- final answer ------------------------------------------------------------
            if not calls:
                checked, validation = await self._check_reply(state, messages, text)
                if hold:
                    yield {"type": "token", "delta": checked}
                final = await repo.add_message(
                    state.conversation,
                    role="assistant",
                    content=checked or FALLBACK_REPLY,
                    language=state.language,
                    input_mode=state.input_mode,
                    meta={"tools_used": list(dict.fromkeys(state.tools_used)), "model": used_model, "usage": usage, "intent": state.intent, **({"validation": validation} if validation else {})},
                )
                state.execution.assistant_message_id = final.id
                yield message_event(final)
                return

            # ---- the model asked for tools -----------------------------------------------
            if hold and text:
                yield {"type": "token", "delta": text}  # the short lead-in ("one moment") before a tool runs
            assistant = await repo.add_message(
                state.conversation,
                role="assistant",
                content=text,
                language=state.language,
                input_mode=state.input_mode,
                tool_calls=[c.as_openai() for c in calls[:MAX_TOOL_CALLS_PER_STEP]],
                meta={"interim": True, "model": used_model},
            )
            yield message_event(assistant)
            yield {"type": "stage", "stage": "tool"}

            step_logs: list[ToolExecutionLog] = []
            paused = False
            for call in calls[:MAX_TOOL_CALLS_PER_STEP]:
                if paused:  # another call is waiting on the user: skip the rest, tell the model why
                    await self._tool_message(repo, state, call.id, call.name, {"status": "skipped", "reason": "Waiting for the user to confirm a previous action."})
                    continue
                state.execution.intent = state.execution.intent or call.name
                entry, outcome_paused = None, False
                async for ev in self._handle_call(state, repo, assistant.id, call):
                    if ev["type"] == "_log":
                        entry = ev["log"]
                        step_logs.append(entry)
                        continue
                    if ev["type"] == "confirmation_required":
                        outcome_paused = True
                    yield ev
                paused = paused or outcome_paused

            if paused:
                if not assistant.content:
                    pending = next(l for l in step_logs if l.status == "awaiting_confirmation")
                    assistant.content = f"I'm ready to do the following: {pending.explanation}. Please confirm to continue."
                state.awaiting_confirmation = True
                state.execution.status = "awaiting_confirmation"
                await state.session.flush()
                yield message_event(assistant, step_logs)
                return

            yield message_event(assistant, step_logs)
            yield {"type": "stage", "stage": "responding"}

        # ---- step limit reached --------------------------------------------------------------
        final = await repo.add_message(
            state.conversation,
            role="assistant",
            content="I'm sorry, I could not finish this in a few steps. Could you rephrase or break it into smaller parts?",
            language=state.language,
            meta={"tools_used": list(dict.fromkeys(state.tools_used)), "step_limit": True},
        )
        state.execution.assistant_message_id = final.id
        yield message_event(final)

    # ---------------------------------------------------------------- one tool call
    async def _handle_call(self, state: TurnState, repo: ConversationRepository, assistant_id, call) -> AsyncIterator[dict[str, Any]]:
        exec_repo = ExecutionRepository(state.session)
        tool = self.registry.get(call.name)

        raw_args: dict[str, Any] = {}
        try:
            raw_args = json.loads(call.arguments) if call.arguments.strip() else {}
        except ValueError:
            pass

        async def failed(msg: str):
            entry = await exec_repo.add_tool_log(
                execution=state.execution, assistant_message_id=assistant_id, tool_call_id=call.id, tool_name=call.name,
                arguments=raw_args if isinstance(raw_args, dict) else {}, status="error", requires_confirmation=False,
            )
            entry.error, entry.summary = msg, msg
            await self._tool_message(repo, state, call.id, call.name, {"error": msg})
            return entry

        if tool is None or not tool.enabled(self.s):
            entry = await failed(f"Unknown or unavailable tool '{call.name}'")
            yield {"type": "_log", "log": entry}
            yield tool_event("tool_result", entry)
            return

        try:
            args = self.registry.parse_args(tool, call.arguments)
        except ToolError as exc:
            entry = await failed(str(exc))
            yield {"type": "_log", "log": entry}
            yield tool_event("tool_result", entry)
            return

        arguments = args.model_dump(mode="json")

        if tool.requires_confirmation:
            entry = await exec_repo.add_tool_log(
                execution=state.execution, assistant_message_id=assistant_id, tool_call_id=call.id, tool_name=tool.name,
                arguments=arguments, status="awaiting_confirmation", requires_confirmation=True,
                explanation=await tool.explain(args, self._tool_ctx(state)),
            )
            yield {"type": "_log", "log": entry}
            yield tool_event("confirmation_required", entry)
            return

        entry = await exec_repo.add_tool_log(
            execution=state.execution, assistant_message_id=assistant_id, tool_call_id=call.id, tool_name=tool.name,
            arguments=arguments, status="running", requires_confirmation=False,
        )
        yield {"type": "_log", "log": entry}
        yield tool_event("tool_start", entry)
        ctx = self._tool_ctx(state)
        outcome = await self.registry.execute(tool, args, ctx)
        self._apply_outcome(entry, outcome)
        if outcome.status == "success":
            state.tools_used.append(tool.name)
            await self._remember(state, tool.name, arguments, outcome.data)
        await self._tool_message(repo, state, call.id, tool.name, outcome.data)
        yield tool_event("tool_result", entry)
        if ctx.language_changed_to:
            state.language = ctx.language_changed_to
            yield {"type": "language", "language": state.language, "changed": True}

    @staticmethod
    def _apply_outcome(entry: ToolExecutionLog, outcome) -> None:
        entry.status = outcome.status
        entry.result = outcome.data
        entry.summary = outcome.summary
        entry.error = outcome.error
        entry.duration_ms = outcome.duration_ms

    @staticmethod
    async def _tool_message(repo: ConversationRepository, state: TurnState, call_id: str, name: str, data: dict[str, Any]) -> None:
        await repo.add_message(
            state.conversation, role="tool", content=json.dumps(data, ensure_ascii=False, default=str), tool_call_id=call_id, tool_name=name
        )

    # ---------------------------------------------------------------- confirmation handling
    async def resolve_confirmation(self, state: TurnState, entry: ToolExecutionLog, approve: bool) -> AsyncIterator[dict[str, Any]]:
        """Run (or decline) a tool that was waiting for the user's decision."""
        repo = ConversationRepository(state.session)
        if not approve:
            entry.status, entry.summary = "denied", "Declined by the user"
            await self._tool_message(repo, state, entry.tool_call_id, entry.tool_name, {"status": "cancelled", "reason": "The user declined this action."})
            yield tool_event("tool_result", entry)
            return

        tool = self.registry.get(entry.tool_name)
        try:
            if tool is None:
                raise ToolError(f"Tool '{entry.tool_name}' is no longer available")
            args = self.registry.parse_args(tool, json.dumps(entry.arguments))
        except ToolError as exc:
            entry.status, entry.error, entry.summary = "error", str(exc), str(exc)
            await self._tool_message(repo, state, entry.tool_call_id, entry.tool_name, {"error": str(exc)})
            yield tool_event("tool_result", entry)
            return

        entry.status, entry.confirmed_at = "running", utcnow()
        yield tool_event("tool_start", entry)
        outcome = await self.registry.execute(tool, args, self._tool_ctx(state))
        self._apply_outcome(entry, outcome)
        if outcome.status == "success":
            state.tools_used.append(tool.name)
            await self._remember(state, tool.name, dict(entry.arguments or {}), outcome.data)
        await self._tool_message(repo, state, entry.tool_call_id, entry.tool_name, outcome.data)
        yield tool_event("tool_result", entry)

    async def cancel_pending(self, state: TurnState, pending: list[ToolExecutionLog]) -> None:
        """The user moved on without confirming: close the dangling tool calls so history stays valid."""
        repo = ConversationRepository(state.session)
        for entry in pending:
            entry.status, entry.summary = "cancelled", "Not confirmed"
            await self._tool_message(repo, state, entry.tool_call_id, entry.tool_name, {"status": "cancelled", "reason": "The user did not confirm."})

