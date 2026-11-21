from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_speech_service
from app.core.config import Settings
from app.core.errors import BadRequest
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import User
from app.database.repositories.users import UserRepository
from app.schemas.misc import SynthesizeIn, TranscribeOut
from app.services.speech_service import SpeechService

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/transcribe", response_model=TranscribeOut)
async def transcribe(
    audio: UploadFile = File(..., description="16-bit PCM mono WAV"),
    language: str = Form(default="en"),
    user: User = Depends(get_current_user),
    speech: SpeechService = Depends(get_speech_service),
    settings: Settings = Depends(get_app_settings),
) -> TranscribeOut:
    # Read at most limit+1 bytes so an oversized upload is rejected without buffering all of it.
    data = await audio.read(settings.max_audio_bytes + 1)
    result = await speech.transcribe(data, language)
    if not result.text:
        raise BadRequest("No speech was recognised. Please try again, closer to the microphone.", code="no_speech")
    return TranscribeOut(text=result.text, language=result.language, duration_seconds=result.duration_seconds)


@router.post("/synthesize", responses={200: {"content": {"audio/wav": {}}}})
async def synthesize(
    body: SynthesizeIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
    speech: SpeechService = Depends(get_speech_service),
) -> Response:
    gender = body.gender or (await UserRepository(session).get_preferences(user.id)).tts_gender
    wav = await speech.synthesize(body.text, body.language, gender)
    return Response(content=wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})
