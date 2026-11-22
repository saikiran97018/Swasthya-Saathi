from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import User, UserPreference
from app.database.repositories.users import UserRepository
from app.schemas.misc import LanguageOut, PreferencesOut, PreferencesUpdate
from app.utils.language import LANGUAGES, is_supported

router = APIRouter(tags=["preferences"])


async def _out(repo: UserRepository, user: User, request: Request) -> PreferencesOut:
    prefs: UserPreference = await repo.get_preferences(user.id)
    langs = await repo.get_languages(user.id)
    base = PreferencesOut.model_validate(prefs)
    base.sms_available = request.app.state.settings.sms_configured
    base.primary_language = next((l.language_code for l in langs if l.is_primary), "en")
    base.secondary_languages = [l.language_code for l in langs if not l.is_primary]
    return base


@router.get("/languages", response_model=list[LanguageOut])
async def languages(request: Request) -> list[LanguageOut]:
    """Supported languages; `asr` / `tts` say whether the ACTIVE speech provider can listen / speak that language."""
    speech = request.app.state.speech_service
    out = []
    for l in LANGUAGES.values():
        asr, tts = speech.capabilities(l.code)
        out.append(LanguageOut(code=l.code, name=l.name, native_name=l.native_name, asr=asr, tts=tts))
    return out


@router.get("/preferences", response_model=PreferencesOut)
async def get_preferences(request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> PreferencesOut:
    return await _out(UserRepository(session), user, request)


@router.put("/preferences", response_model=PreferencesOut)
async def update_preferences(body: PreferencesUpdate, request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> PreferencesOut:
    repo = UserRepository(session)
    prefs = await repo.get_preferences(user.id)
    data = body.model_dump(exclude_unset=True)
    primary = data.pop("primary_language", None)
    secondary = data.pop("secondary_languages", None)
    for key, value in data.items():
        if value is not None:
            setattr(prefs, key, value)

    if primary is not None or secondary is not None:
        current = await repo.get_languages(user.id)
        new_primary = primary or next((l.language_code for l in current if l.is_primary), "en")
        new_secondary = secondary if secondary is not None else [l.language_code for l in current if not l.is_primary]
        for code in [new_primary, *new_secondary]:
            if not is_supported(code):
                raise BadRequest(f"Unsupported language '{code}'", code="language_not_supported")
        await repo.set_languages(user.id, new_primary, list(dict.fromkeys(new_secondary)))
    await session.flush()
    return await _out(repo, user, request)

