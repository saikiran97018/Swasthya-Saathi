"""Agent execution + tool execution log persistence."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AgentExecution, ToolExecutionLog


class ExecutionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def start(self, *, conversation_id: uuid.UUID, user_id: uuid.UUID, user_message_id: uuid.UUID | None, model: str | None) -> AgentExecution:
        ex = AgentExecution(conversation_id=conversation_id, user_id=user_id, user_message_id=user_message_id, model=model, status="running")
        self.session.add(ex)
        await self.session.flush()
        return ex

    async def get_execution(self, execution_id: uuid.UUID) -> AgentExecution | None:
        return await self.session.get(AgentExecution, execution_id)

    async def add_tool_log(
        self,
        *,
        execution: AgentExecution,
        assistant_message_id: uuid.UUID | None,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        status: str,
        requires_confirmation: bool,
        explanation: str | None = None,
    ) -> ToolExecutionLog:
        log = ToolExecutionLog(
            execution_id=execution.id,
            conversation_id=execution.conversation_id,
            user_id=execution.user_id,
            assistant_message_id=assistant_message_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            status=status,
            requires_confirmation=requires_confirmation,
            explanation=explanation,
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def get_tool_log(self, log_id: uuid.UUID, user_id: uuid.UUID) -> ToolExecutionLog | None:
        log = await self.session.get(ToolExecutionLog, log_id)
        return log if log and log.user_id == user_id else None

    async def pending_logs(self, conversation_id: uuid.UUID) -> list[ToolExecutionLog]:
        rows = await self.session.execute(
            select(ToolExecutionLog).where(
                ToolExecutionLog.conversation_id == conversation_id, ToolExecutionLog.status == "awaiting_confirmation"
            )
        )
        return list(rows.scalars().all())

    async def list_executions(
        self, user_id: uuid.UUID, *, conversation_id: uuid.UUID | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[AgentExecution], int]:
        stmt = select(AgentExecution).where(AgentExecution.user_id == user_id)
        if conversation_id:
            stmt = stmt.where(AgentExecution.conversation_id == conversation_id)
        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await self.session.execute(stmt.order_by(AgentExecution.started_at.desc()).limit(limit).offset(offset))).scalars().all()
        return list(rows), total

    async def logs_for_executions(self, execution_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ToolExecutionLog]]:
        if not execution_ids:
            return {}
        rows = (
            await self.session.execute(
                select(ToolExecutionLog).where(ToolExecutionLog.execution_id.in_(execution_ids)).order_by(ToolExecutionLog.created_at)
            )
        ).scalars().all()
        out: dict[uuid.UUID, list[ToolExecutionLog]] = {}
        for r in rows:
            out.setdefault(r.execution_id, []).append(r)
        return out

    async def tool_stats(self, user_id: uuid.UUID) -> list[tuple[str, int]]:
        rows = await self.session.execute(
            select(ToolExecutionLog.tool_name, func.count()).where(ToolExecutionLog.user_id == user_id).group_by(ToolExecutionLog.tool_name)
        )
        return [(name, n) for name, n in rows.all()]
