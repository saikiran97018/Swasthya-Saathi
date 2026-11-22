"""A short note for the doctor, built from what the patient said in a conversation."""
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import User
from app.database.repositories.conversations import ConversationRepository
from app.services import working_memory
from app.services.doctor_summary import write_note

router = APIRouter(tags=["conversations"])


class DoctorNoteOut(BaseModel):
    text: str
    source: str  # assistant | basic


@router.post("/conversations/{conversation_id}/doctor-note", response_model=DoctorNoteOut)
async def doctor_note(conversation_id: uuid.UUID, request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> DoctorNoteOut:
    """Only the person's own messages are used. The note never contains a diagnosis or advice."""
    repo = ConversationRepository(session)
    conv = await repo.get_owned(conversation_id, user.id)
    said = [m.content for m in await repo.list_messages(conv.id) if m.role == "user" and m.content]
    memory = (await repo.get_meta(conv)).extra.get(working_memory.KEY) or {}
    await session.commit()  # do not hold a transaction open while the model writes
    text, source = await write_note(request.app.state.llm, said, memory)
    return DoctorNoteOut(text=text, source=source)
