"""Live voice calls: start / stop a call, and the OpenAI-compatible endpoint Agora's cloud agent uses as its "brain"."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import build_system_prompt
from app.services.billing import check_call_allowed
from app.utils.transcript import check_transcript
from app.api.deps import get_app_settings
from app.core.config import Settings
from app.core.errors import AppError, Unauthorized
from app.core.security import get_current_user
from app.database.connection import get_session, get_session_factory
from app.database.models import User
from app.database.repositories.conversations import ConversationRepository
from app.database.repositories.executions import ExecutionRepository
from app.database.repositories.family import FamilyRepository
from app.schemas.agora import AgoraStatus, CallLanguageOut, CallStartIn, CallStartOut, CallVoice
from app.services.agora import LANGUAGES, AgoraService, language_for, make_llm_token, new_call_ids, read_llm_token, voice_for
from app.utils.yesno import quick_yes_no

log = logging.getLogger("app.agora")
router = APIRouter(prefix="/agora", tags=["agora"])

NO_TOOLS = (
    "\nIn this call you have NO tools: never claim to have booked, saved, looked up or sent anything. "
    "For those, tell the user to use the Doctors or chat screen in the app. You can still give general guidance, and in an emergency tell them to call 112."
)


def _service(request: Request) -> AgoraService:
    return request.app.state.agora


@router.get("/status", response_model=AgoraStatus)
async def status(settings: Settings = Depends(get_app_settings), user: User = Depends(get_current_user)) -> AgoraStatus:
    missing = [n for n, ok in (("AGORA_APP_ID", bool(settings.agora_app_id)), ("AGORA_APP_CERTIFICATE", bool(settings.agora_app_certificate)), ("MURF_API_KEY", settings.murf_configured)) if not ok]
    mode = settings.agora_mode
    note = None
    if mode == "unconfigured":
        note = f"Live calls need {', '.join(missing)} in backend/.env, then a backend restart."
    elif mode == "chat_only":
        note = "This call can talk, but it cannot find clinics or save visits until the server has a public HTTPS address (AGORA_PUBLIC_URL)."
    return AgoraStatus(
        configured=mode != "unconfigured", murf_configured=settings.murf_configured, mode=mode,  # type: ignore[arg-type]
        languages=[CallLanguageOut(code=l.code, name=l.name, native_name=l.native_name, voice=voice_for(settings, l)) for l in LANGUAGES.values()], note=note,
    )


@router.post("/session", response_model=CallStartOut, status_code=201)
async def start_call(
    request: Request, body: CallStartIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function"),
    settings: Settings = Depends(get_app_settings),
) -> CallStartOut:
    svc = _service(request)
    svc._require()
    await check_call_allowed(session, settings, user)  # free plan: a daily limit (no-op until Razorpay is set up)
    lang = language_for(settings, body.language)

    repo = ConversationRepository(session)
    if body.conversation_id:
        conv = await repo.get_owned(body.conversation_id, user.id)
        conv.language = lang.code
    else:
        conv = await repo.create(user.id, title="Live call", language=lang.code)
    await session.commit()  # the agent will call back into this server: the conversation must already be saved

    channel, user_uid, agent_uid = new_call_ids()
    family = [f"{m.name} ({m.relation})" for m in await FamilyRepository(session).list(user.id)]
    system_prompt = build_system_prompt(language=lang.code, summary=None, voice=True, display_name=user.display_name, family=family) + NO_TOOLS
    llm, mode = svc.llm_config(lang=lang, system_prompt=system_prompt, session_token=make_llm_token(settings, user_id=str(user.id), conversation_id=str(conv.id), language=lang.code))
    agent_token = svc.agent_token(channel, agent_uid)
    join = svc.build_join_body(lang=lang, channel=channel, agent_uid=agent_uid, user_uid=user_uid, token=agent_token, llm=llm, name=f"swasthya-{channel}")
    started = await svc.start(join, agent_token)

    sessions: dict[str, dict[str, Any]] = request.app.state.agora_sessions
    for key in [k for k, v in sessions.items() if time.time() - v["at"] > 4 * 3600]:
        sessions.pop(key, None)
    sessions[started["agent_id"]] = {"user_id": user.id, "channel": channel, "agent_uid": agent_uid, "at": time.time()}
    log.info("Live call started: mode=%s language=%s", mode, lang.code)
    return CallStartOut(
        app_id=settings.agora_app_id, channel=channel, token=svc.client_token(channel, user_uid), uid=user_uid, agent_uid=agent_uid, agent_id=started["agent_id"],
        conversation_id=conv.id, language=lang.code, mode=mode, expires_in=settings.agora_session_minutes * 60,  # type: ignore[arg-type]
        greeting=lang.greeting, voice=CallVoice(voice_id=voice_for(settings, lang), locale=lang.locale),
    )


@router.post("/session/{agent_id}/stop", status_code=204)
async def stop_call(agent_id: str, request: Request, user: User = Depends(get_current_user)) -> Response:
    """Hang up. Safe to call twice; a call that is already over (or unknown after a restart) just returns 204."""
    sessions: dict[str, dict[str, Any]] = request.app.state.agora_sessions
    info = sessions.get(agent_id)
    if info is None or info["user_id"] != user.id:
        return Response(status_code=204)
    svc = _service(request)
    try:
        await svc.stop(agent_id, svc.agent_token(info["channel"], info["agent_uid"]))
    finally:
        sessions.pop(agent_id, None)
    return Response(status_code=204)


# ===================================================================================== the agent's brain (OpenAI-compatible)
def _last_user_text(messages: Any) -> str:
    for m in reversed(messages if isinstance(messages, list) else []):
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):  # OpenAI "parts" form
                return " ".join(p.get("text", "") for p in content if isinstance(p, dict)).strip()
    return ""


def _chunk(text: str | None = None, *, finish: bool = False, first: bool = False) -> str:
    delta: dict[str, Any] = {}
    if first:
        delta["role"] = "assistant"
    if text:
        delta["content"] = text
    obj = {"id": "chatcmpl-swasthya", "object": "chat.completion.chunk", "created": int(time.time()), "model": "swasthya-saathi",
           "choices": [{"index": 0, "delta": delta, "finish_reason": "stop" if finish else None}]}
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


async def _verdict(text: str, llm) -> str:
    quick = quick_yes_no(text)
    if quick != "other":
        return quick
    try:  # unclear: let the language model judge (it understands every language here)
        answer = await llm.complete(
            [{"role": "system", "content": "The user was asked to confirm an action. Reply with exactly one word: YES if they agree, NO if they refuse or want to cancel, OTHER if unclear."},
             {"role": "user", "content": text}], temperature=0, max_tokens=5,
        )
    except AppError:
        return "other"
    word = answer.strip().upper()
    return "yes" if word.startswith("YES") else "no" if word.startswith("NO") else "other"


@router.post("/llm/chat/completions")
async def llm_for_agent(request: Request) -> StreamingResponse:
    """Agora's cloud agent calls this with the caller's transcribed words and speaks whatever streams back.

    Each call carries a token that is only valid for this one call (signed with a key derived from, but different from, the
    login secret), so the token Agora holds can never be used to log in. The caller's words go through the normal assistant, so
    tools, safety rules and the confirm-before-acting gate all apply; a spoken yes or no answers a pending confirmation.
    """
    settings: Settings = request.app.state.settings
    header = request.headers.get("authorization", "")
    ctx = read_llm_token(settings, header[7:] if header.lower().startswith("bearer ") else None)
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    text = _last_user_text(payload.get("messages"))
    lang = LANGUAGES.get(ctx["language"], LANGUAGES["en"])
    locks: defaultdict[str, asyncio.Lock] = request.app.state.agora_locks
    agent, llm = request.app.state.agent_service, request.app.state.llm
    cid = uuid.UUID(ctx["conversation_id"])

    async def stream() -> AsyncIterator[str]:
        yield _chunk(first=True)
        heard = check_transcript(text) if text else None
        if heard is not None and heard.ok:
            text_clean = heard.text
        else:
            text_clean = ""  # silence, a filler sound or a recogniser's invented caption: stay quiet instead of answering nobody
        if not text_clean:
            yield _chunk(finish=True) + "data: [DONE]\n\n"
            return
        try:
            async with locks[ctx["conversation_id"]]:  # one turn at a time per call, even if the caller interrupts
                async with get_session_factory()() as session:
                    user = await session.get(User, uuid.UUID(ctx["user_id"]))
                    if user is None:
                        raise Unauthorized("User no longer exists")
                    pending = await ExecutionRepository(session).pending_logs(cid)
                    if pending:
                        verdict = await _verdict(text_clean, llm)
                        if verdict == "other":
                            yield _chunk(lang.confirm_ask)
                            events: AsyncIterator[dict[str, Any]] | None = None
                        else:
                            events = agent.confirm(session, user, tool_execution_id=pending[-1].id, approve=verdict == "yes", voice_output=True)
                    else:
                        events = agent.handle_message(session, user, conversation_id=cid, text=text_clean, input_mode="voice", language=lang.code, voice_output=True)
                    if events is not None:
                        async for ev in events:
                            if ev["type"] == "token":
                                yield _chunk(ev["delta"])
                            elif ev["type"] == "confirmation_required":
                                yield _chunk(" " + lang.confirm_ask)
                            elif ev["type"] == "error":
                                log.warning("voice turn failed: %s", ev.get("code"))
                                yield _chunk(lang.failure)
        except Unauthorized:
            yield _chunk(lang.failure)
        except Exception:  # never leave the caller in silence
            log.exception("voice turn crashed")
            yield _chunk(lang.failure)
        yield _chunk(finish=True)
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
