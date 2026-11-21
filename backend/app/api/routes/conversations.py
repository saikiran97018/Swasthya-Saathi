import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import User
from app.database.repositories.conversations import ConversationRepository
from app.database.repositories.users import UserRepository
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationPage,
    ConversationUpdate,
    MessageOut,
)
from app.utils.language import normalise_language

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationPage)
async def list_conversations(
    q: str | None = Query(default=None, max_length=100, description="Search titles and message text"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> ConversationPage:
    repo = ConversationRepository(session)
    rows, total = await repo.list_for_user(user.id, q=q, limit=limit, offset=offset)
    items = [ConversationOut.from_model(c, await repo.get_meta(c)) for c in rows]
    return ConversationPage(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=ConversationOut, status_code=201)
async def create_conversation(
    body: ConversationCreate | None = None, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")
) -> ConversationOut:
    repo = ConversationRepository(session)
    lang = normalise_language(body.language if body else None, await UserRepository(session).primary_language(user.id))
    title = body.title.strip() if body and body.title and body.title.strip() else "New conversation"
    conv = await repo.create(user.id, title=title, language=lang, title_is_auto=not (body and body.title))
    return ConversationOut.from_model(conv, await repo.get_meta(conv))


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> ConversationDetail:
    repo = ConversationRepository(session)
    conv = await repo.get_owned(conversation_id, user.id)
    messages = [m for m in await repo.list_messages(conv.id) if m.role in ("user", "assistant")]
    logs = await repo.tool_logs_for_messages([m.id for m in messages if m.role == "assistant"])
    base = ConversationOut.from_model(conv, await repo.get_meta(conv))
    return ConversationDetail(**base.model_dump(), messages=[MessageOut.from_model(m, logs.get(m.id)) for m in messages])


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")
) -> ConversationOut:
    repo = ConversationRepository(session)
    conv = await repo.rename(await repo.get_owned(conversation_id, user.id), body.title)
    return ConversationOut.from_model(conv, await repo.get_meta(conv))


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> Response:
    repo = ConversationRepository(session)
    await repo.delete(await repo.get_owned(conversation_id, user.id))
    return Response(status_code=204)
