"""Chat endpoints: REST (`POST /chat`) and the streaming WebSocket (`/ws/chat`)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_agent_service, get_app_settings
from app.core.config import Settings
from app.core.errors import AppError, BadRequest
from app.core.security import authenticate_token, get_current_user
from app.database.connection import get_session, get_session_factory
from app.database.models import User
from app.schemas.conversation import ConversationOut, MessageOut, ToolExecutionOut
from app.schemas.misc import ChatIn, ChatOut
from app.services.agent_service import AgentService

log = logging.getLogger("app.chat")
router = APIRouter(tags=["chat"])


def _status_for(code: str) -> int:
    if code.endswith("not_configured"):
        return 503
    if code.startswith(("llm_", "bhashini", "sarvam")):
        return 502
    if code == "internal_error":
        return 500
    return 400


async def collect_turn(events: AsyncIterator[dict[str, Any]], session: AsyncSession, user: User, fallback_conversation: uuid.UUID | None = None) -> ChatOut:
    """Fold a stream of agent events into one REST response."""
    conversation: dict | None = None
    user_message: dict | None = None
    messages: dict[str, dict] = {}
    tool_execs: dict[str, dict] = {}
    pending: dict | None = None
    language, execution_id = "en", None
    async for ev in events:
        t = ev["type"]
        if t == "conversation":
            conversation = ev["conversation"]
        elif t == "user_message":
            user_message = ev["message"]
        elif t == "message":
            messages[ev["message"]["id"]] = ev["message"]  # later versions replace earlier ones
        elif t in ("tool_start", "tool_result", "confirmation_required"):
            tool_execs[ev["tool_execution"]["id"]] = ev["tool_execution"]  # latest state wins
            if t == "confirmation_required":
                pending = ev["tool_execution"]
        elif t == "language":
            language = ev["language"]
        elif t == "done":
            execution_id = ev["execution_id"]
        elif t == "error":
            raise AppError(ev["message"], code=ev["code"], status_code=_status_for(ev["code"]))
    if conversation is None:
        raise BadRequest("Conversation could not be resolved")
    ordered = sorted(messages.values(), key=lambda m: m["seq"])
    visible = [MessageOut.model_validate(m) for m in ordered if m["content"] or m["tool_executions"]]
    final = next((m for m in reversed(visible) if not m.tool_executions or m.content), visible[-1] if visible else None)
    return ChatOut(
        conversation=ConversationOut.model_validate(conversation),
        user_message=MessageOut.model_validate(user_message) if user_message else None,
        assistant_message=final,
        messages=visible,
        tool_executions=[ToolExecutionOut.model_validate(t) for t in tool_execs.values()],
        pending_confirmation=ToolExecutionOut.model_validate(pending) if pending else None,
        language=language,
        execution_id=execution_id,
    )


@router.post("/chat", response_model=ChatOut)
async def chat(
    body: ChatIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
    agent: AgentService = Depends(get_agent_service),
) -> ChatOut:
    if body.regenerate:
        if not body.conversation_id:
            raise BadRequest("conversation_id is required to regenerate")
        events = agent.regenerate(session, user, conversation_id=body.conversation_id, voice_output=body.voice_output)
    else:
        if not body.message:
            raise BadRequest("message is required")
        events = agent.handle_message(
            session, user, conversation_id=body.conversation_id, text=body.message, input_mode=body.input_mode,
            language=body.language, voice_output=body.voice_output,
        )
    return await collect_turn(events, session, user)


# ============================================================================ WebSocket


class WsClientEvent(BaseModel):
    type: Literal["message", "regenerate", "confirm", "cancel", "ping"]
    conversation_id: uuid.UUID | None = None
    text: str | None = Field(default=None, max_length=4000)
    input_mode: Literal["text", "voice"] = "text"
    language: str | None = Field(default=None, max_length=8)
    voice_output: bool = False
    execution_id: uuid.UUID | None = Field(default=None, description="Tool execution id for 'confirm'")
    approve: bool | None = None


@router.websocket("/ws/chat")
async def ws_chat(ws: WebSocket, token: str | None = Query(default=None)) -> None:
    """Real-time chat. Client sends JSON commands, server streams agent events (see docs/API.md)."""
    settings: Settings = ws.app.state.settings
    agent: AgentService = ws.app.state.agent_service
    factory = get_session_factory()

    await ws.accept()
    try:
        async with factory() as session:
            user_id = (await authenticate_token(session, token)).id
    except AppError as exc:
        await ws.send_json({"type": "error", "code": exc.code, "message": exc.message, "retryable": False})
        await ws.close(code=4401)
        return

    current: asyncio.Task | None = None
    turn_active = False  # true from accepting a command until its final event ("done"/"error"/"cancelled") is sent
    recent_turns: deque[float] = deque()

    async def send(ev: dict[str, Any]) -> None:
        await ws.send_json(ev)

    async def send_turn_event(ev: dict[str, Any]) -> None:
        """Send an event from a running turn; the last one frees the connection for the next command."""
        nonlocal turn_active
        if ev["type"] in ("done", "error", "cancelled"):
            turn_active = False  # clear first: the client may reply the instant it receives this
        await ws.send_json(ev)

    def release_connection() -> None:
        nonlocal turn_active
        turn_active = False

    async def run_turn(cmd: WsClientEvent) -> None:
        try:
            async with factory() as session:
                user = await session.get(User, user_id)
                if user is None:
                    raise BadRequest("User no longer exists")
                if cmd.type == "message":
                    events = agent.handle_message(
                        session, user, conversation_id=cmd.conversation_id, text=cmd.text or "", input_mode=cmd.input_mode,
                        language=cmd.language, voice_output=cmd.voice_output,
                    )
                elif cmd.type == "regenerate":
                    if not cmd.conversation_id:
                        raise BadRequest("conversation_id is required")
                    events = agent.regenerate(session, user, conversation_id=cmd.conversation_id, voice_output=cmd.voice_output)
                else:  # confirm
                    if not cmd.execution_id or cmd.approve is None:
                        raise BadRequest("execution_id and approve are required")
                    events = agent.confirm(session, user, tool_execution_id=cmd.execution_id, approve=cmd.approve, voice_output=cmd.voice_output)
                async for ev in events:
                    await send_turn_event(ev)
        except asyncio.CancelledError:
            await send_turn_event({"type": "cancelled"})
            raise
        except AppError as exc:
            await send_turn_event({"type": "error", "code": exc.code, "message": exc.message, "retryable": getattr(exc, "retryable", False)})
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("websocket turn failed")
            await send_turn_event({"type": "error", "code": "internal_error", "message": "Something went wrong. Please try again.", "retryable": True})
        finally:
            release_connection()

    try:
        while True:
            raw = await ws.receive_json()
            try:
                cmd = WsClientEvent.model_validate(raw)
            except ValidationError as exc:
                await send({"type": "error", "code": "invalid_message", "message": exc.errors()[0]["msg"], "retryable": False})
                continue

            if cmd.type == "ping":
                await send({"type": "pong"})
            elif cmd.type == "cancel":
                if current and turn_active and not current.done():
                    current.cancel()
            else:
                if turn_active:
                    await send({"type": "error", "code": "busy", "message": "Still working on the previous message.", "retryable": True})
                    continue
                now = asyncio.get_running_loop().time()
                while recent_turns and now - recent_turns[0] > 60:
                    recent_turns.popleft()
                if len(recent_turns) >= settings.rate_limit_ai_per_minute:
                    await send({"type": "error", "code": "rate_limited", "message": "Too many messages. Please wait a moment.", "retryable": True})
                    continue
                recent_turns.append(now)
                turn_active = True
                current = asyncio.create_task(run_turn(cmd))
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("websocket loop failed")
    finally:
        if current and not current.done():
            current.cancel()
            try:
                await current
            except (asyncio.CancelledError, Exception):
                pass

