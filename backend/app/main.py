"""FastAPI application factory.

`create_app()` wires settings, the database, services, middleware and routes. Tests call it
with fake HTTP clients so no real Bhashini / LLM / internet access is needed.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.agents.orchestrator import AgentOrchestrator
from app.agents.tools import build_registry
from app.api.routes import agents, agora, appointments, auth, billing, chat, conversations, dashboard, doctor_note, family, health, medicine, message_feedback, notifications, places, preferences, providers, push, sos, tasks, vaccines, voice
from app.core.config import Settings, get_settings
from app.core.errors import AppError, NotFound
from app.core.logging import install_log_redaction, setup_logging
from app.database import connection
from app.database.models import Base
from app.database.seed import seed_if_empty
from app.services.agora import AgoraService
from app.services.places import PlacesService
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.services.agent_service import AgentService
from app.services.bhashini_service import BhashiniService
from app.services.sarvam_service import SarvamService
from app.services.speech_failover import FailoverSpeechProvider
from app.services.llm_service import LLMService
from app.core.security_headers import SecurityHeadersMiddleware
from app.services.billing import BillingService
from app.services.push import PushService
from app.services.rag import RagService
from app.services.reminder_service import ReminderService
from app.services.speech_service import SpeechService

log = logging.getLogger("app")


def create_app(
    settings: Settings | None = None,
    *,
    llm_client: httpx.AsyncClient | None = None,
    bhashini_client: httpx.AsyncClient | None = None,
    tools_client: httpx.AsyncClient | None = None,
    sarvam_client: httpx.AsyncClient | None = None,
    llm_fallback_client: httpx.AsyncClient | None = None,
    places_client: httpx.AsyncClient | None = None,
    agora_client: httpx.AsyncClient | None = None,
    billing_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        install_log_redaction()  # after uvicorn configured its loggers
        engine = connection.init_engine(settings.database_url)
        if settings.auto_create_tables:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        if settings.auto_seed:
            try:
                async with connection.get_session_factory()() as session:
                    await seed_if_empty(session, include_demo_providers=settings.seed_demo_providers)
                    await session.commit()
            except Exception:
                log.exception("Seeding skipped (have you run `alembic upgrade head`?)")

        http = tools_client or httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "BharatVoiceAgent/1.0"})
        llm = LLMService(settings, llm_client, llm_fallback_client)
        def build_speech(name: str):
            return SarvamService(settings, sarvam_client) if name == "sarvam" else BhashiniService(settings, bhashini_client)

        speech_provider = build_speech(settings.resolved_speech_provider)
        backup = settings.resolved_speech_fallback
        if backup:  # e.g. Bhashini first, Sarvam if Bhashini fails
            speech_provider = FailoverSpeechProvider(speech_provider, build_speech(backup))
        registry = build_registry()
        push_service = PushService(settings)
        app.state.push = push_service
        app.state.billing = BillingService(settings, billing_client or http)
        reminders = ReminderService(settings, llm, http, push_service)
        places_service = PlacesService(settings, places_client or http)
        app.state.places = places_service
        app.state.agora = AgoraService(settings, agora_client or http)
        app.state.agora_sessions = {}  # agent_id -> who started the call (so only they can hang it up)
        app.state.agora_locks = defaultdict(asyncio.Lock)  # one spoken turn at a time per call
        app.state.settings = settings
        app.state.registry = registry
        app.state.http = http
        app.state.llm = llm
        app.state.speech_provider = speech_provider
        app.state.reminder_service = reminders
        app.state.speech_service = SpeechService(settings, speech_provider)
        app.state.agent_service = AgentService(settings, llm, AgentOrchestrator(llm, registry, settings, http, places_service, RagService(settings, llm)))
        loop_task = asyncio.create_task(reminders.run_forever()) if settings.reminder_poll_seconds > 0 else None
        log.info(
            "%s started (env=%s, llm=%s%s, speech=%s configured=%s)", settings.app_name, settings.environment, settings.llm_model,
            f" -> fallback {settings.llm_fallback_model}" if settings.llm_fallback_configured else "",
            f"{speech_provider.name} (backup {speech_provider.fallback_name})" if backup else speech_provider.name, speech_provider.configured,
        )
        try:
            yield
        finally:
            if loop_task:
                loop_task.cancel()
                try:
                    await loop_task
                except asyncio.CancelledError:
                    pass
            await llm.aclose()
            await speech_provider.aclose()
            await http.aclose()
            await connection.dispose_engine()

    app = FastAPI(
        title=settings.app_name,
        version=health.VERSION,
        description="Multilingual, voice-first agentic healthcare assistant (Bhashini STT/TTS + open-source LLM + tool calling).",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    # Middleware order: the last added runs first (outermost).
    app.add_middleware(
        RateLimitMiddleware,
        api_prefix=settings.api_prefix,
        general_per_minute=settings.rate_limit_per_minute,
        ai_per_minute=settings.rate_limit_ai_per_minute,
        trust_proxy=settings.trust_proxy_headers,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Invalid request", "details": details}})

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Internal server error", "details": None}})

    prefix = settings.api_prefix
    for module in (health, auth, conversations, chat, voice, agents, appointments, providers, notifications, tasks, preferences, dashboard, family, sos, places, agora, push, billing, medicine, message_feedback, vaccines, doctor_note):
        app.include_router(module.router, prefix=prefix)

    if settings.static_dir:  # registered last, so every API route and /docs win over the web app's catch-all
        _serve_web_app(app, Path(settings.static_dir), prefix)

    return app


def _serve_web_app(app: FastAPI, root: Path, api_prefix: str) -> None:
    """Serve the built web app (and its client-side routes such as /sos or /call) from this same server."""
    index = root / "index.html"
    if not index.is_file():
        log.warning("STATIC_DIR=%s has no index.html: the web app will not be served (build it with `npm run build`)", root)
        return
    root = root.resolve()
    api = api_prefix.strip("/")

    @app.get("/{path:path}", include_in_schema=False)
    async def web_app(path: str) -> FileResponse:
        if path == api or path.startswith(api + "/"):  # an unknown API address is a real 404, never the web page
            raise NotFound("No such API route", code="route_not_found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:  # a real file (script, image, icon); never outside the folder
            long_lived = path.startswith("assets/")  # build output has a content hash in its name
            return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable" if long_lived else "no-cache"})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})  # any other path is a page of the app


app = create_app()

