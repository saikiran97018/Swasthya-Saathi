from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings
from app.core.config import Settings
from app.database.connection import get_session
from app.schemas.misc import HealthOut

router = APIRouter(tags=["health"])
VERSION = "1.0.0"


@router.get("/health", response_model=HealthOut)
async def health(request: Request, session: AsyncSession = Depends(get_session, scope="function"), settings: Settings = Depends(get_app_settings)) -> HealthOut:
    try:
        await session.execute(text("select 1"))
        db_ok = True
    except Exception:
        db_ok = False
    speech = request.app.state.speech_service
    return HealthOut(
        status="ok" if db_ok else "degraded",
        database=db_ok,
        speech_provider=speech.provider.name,
        speech_fallback_provider=getattr(speech.provider, "fallback_name", None),
        speech_configured=speech.provider.configured,
        max_audio_seconds=speech.max_audio_seconds,
        bhashini_configured=settings.bhashini_configured,
        sarvam_configured=settings.sarvam_configured,
        llm_configured=settings.llm_configured,
        llm_model=settings.llm_model if settings.llm_primary_configured else settings.llm_fallback_model,
        llm_fallback_model=settings.llm_fallback_model if settings.llm_fallback_configured and settings.llm_primary_configured else None,
        web_search_configured=settings.web_search_configured,
        demo_mode=settings.demo_mode,
        version=VERSION,
    )
