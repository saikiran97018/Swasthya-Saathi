from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.mappers import appointment_out
from app.api.routes.agents import _executions_out
from app.database.repositories.appointments import AppointmentRepository, ReminderRepository
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import Conversation, ConversationMetadata, ToolExecutionLog, User
from app.database.repositories.conversations import ConversationRepository
from app.database.repositories.executions import ExecutionRepository
from app.database.repositories.tasks import TaskRepository
from app.schemas.conversation import ConversationOut
from app.schemas.misc import DashboardOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardOut)
async def summary(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> DashboardOut:
    conv_repo, exec_repo = ConversationRepository(session), ExecutionRepository(session)

    totals = (
        await session.execute(
            select(func.count(Conversation.id), func.coalesce(func.sum(ConversationMetadata.message_count), 0), func.coalesce(func.sum(ConversationMetadata.voice_message_count), 0))
            .select_from(Conversation)
            .join(ConversationMetadata, ConversationMetadata.conversation_id == Conversation.id, isouter=True)
            .where(Conversation.user_id == user.id)
        )
    ).one()
    tool_runs = (await session.execute(select(func.count()).select_from(ToolExecutionLog).where(ToolExecutionLog.user_id == user.id))).scalar_one()
    by_status = await TaskRepository(session).count_by_status(user.id)

    recent, _ = await conv_repo.list_for_user(user.id, limit=5)
    executions, _ = await exec_repo.list_executions(user.id, limit=5)
    appt_repo, reminder_repo = AppointmentRepository(session), ReminderRepository(session)
    upcoming, _ = await appt_repo.list_for_user(user.id, scope="upcoming", limit=3)
    _, _, unread = await reminder_repo.notifications(user.id, limit=1)
    _, appts_total = await appt_repo.list_for_user(user.id, scope="all", limit=1)
    return DashboardOut(
        appointments_total=appts_total,
        unread_notifications=unread,
        upcoming_appointments=[appointment_out(a, await reminder_repo.for_appointment(a.id)) for a in upcoming],
        conversations=totals[0],
        messages=int(totals[1]),
        voice_messages=int(totals[2]),
        tool_runs=tool_runs,
        open_tasks=by_status.get("open", 0) + by_status.get("in_progress", 0),
        submitted_requests=by_status.get("submitted", 0),
        tool_usage=[{"tool": n, "count": c} for n, c in sorted(await exec_repo.tool_stats(user.id), key=lambda t: -t[1])],
        recent_conversations=[ConversationOut.from_model(c, await conv_repo.get_meta(c)) for c in recent],
        recent_executions=await _executions_out(session, executions, exec_repo),
    )
