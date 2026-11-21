import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_agent_service, get_app_settings
from app.api.routes.chat import collect_turn
from app.core.config import Settings
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import Conversation, User
from app.database.repositories.executions import ExecutionRepository
from app.schemas.conversation import ToolExecutionOut
from app.schemas.misc import AgentInfo, AgentToolInfo, ChatOut, ConfirmIn, ExecutionOut, ExecutionPage
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentInfo])
async def list_agents(request: Request, user: User = Depends(get_current_user), settings: Settings = Depends(get_app_settings)) -> list[AgentInfo]:
    registry = request.app.state.registry
    tools = [
        AgentToolInfo(
            name=t.name, description=t.description, category=t.category,
            requires_confirmation=t.requires_confirmation, enabled=t.enabled(settings),
        )
        for t in registry.all_tools()
    ]
    return [
        AgentInfo(
            id="swasthya-saathi",
            name="Swasthya Saathi",
            description="Multilingual healthcare assistant: assesses urgency, finds providers, books appointments, sends reminders, schedules follow-ups and collects feedback.",
            model=settings.llm_model,
            tools=tools,
        )
    ]


async def _executions_out(session: AsyncSession, rows, repo: ExecutionRepository) -> list[ExecutionOut]:
    logs = await repo.logs_for_executions([r.id for r in rows])
    titles = {}
    for r in rows:
        if r.conversation_id not in titles:
            conv = await session.get(Conversation, r.conversation_id)
            titles[r.conversation_id] = conv.title if conv else None
    return [
        ExecutionOut(
            id=r.id, conversation_id=r.conversation_id, conversation_title=titles.get(r.conversation_id), status=r.status,
            intent=r.intent, model=r.model, steps=r.steps, latency_ms=r.latency_ms, error=r.error,
            started_at=r.started_at, finished_at=r.finished_at,
            tool_executions=[ToolExecutionOut.model_validate(l) for l in logs.get(r.id, [])],
        )
        for r in rows
    ]


@router.get("/executions", response_model=ExecutionPage)
async def list_executions(
    conversation_id: uuid.UUID | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> ExecutionPage:
    repo = ExecutionRepository(session)
    rows, total = await repo.list_executions(user.id, conversation_id=conversation_id, limit=limit, offset=offset)
    return ExecutionPage(items=await _executions_out(session, rows, repo), total=total, limit=limit, offset=offset)


@router.post("/executions/{tool_execution_id}/confirm", response_model=ChatOut)
async def confirm_execution(
    tool_execution_id: uuid.UUID,
    body: ConfirmIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
    agent: AgentService = Depends(get_agent_service),
) -> ChatOut:
    """Approve or decline a sensitive tool call that is waiting for the user, then let the agent finish."""
    events = agent.confirm(session, user, tool_execution_id=tool_execution_id, approve=body.approve)
    return await collect_turn(events, session, user)
