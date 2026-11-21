import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest, NotFound
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import User
from app.database.repositories.tasks import TaskRepository
from app.schemas.misc import TaskOut, TaskPage, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskPage)
async def list_tasks(
    status: str | None = Query(default=None, pattern="^(open|in_progress|done|cancelled|submitted)$"),
    kind: str | None = Query(default=None, pattern="^(task|service_request)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> TaskPage:
    rows, total = await TaskRepository(session).list_for_user(user.id, status=status, kind=kind, limit=limit, offset=offset)
    return TaskPage(items=[TaskOut.model_validate(t) for t in rows], total=total, limit=limit, offset=offset)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(task_id: uuid.UUID, body: TaskUpdate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> TaskOut:
    task = await TaskRepository(session).get_owned(user.id, task_id)
    if task is None:
        raise NotFound("Task not found", code="task_not_found")
    if task.kind == "service_request":
        raise BadRequest("Submitted service requests cannot be edited", code="service_request_locked")
    task.status = body.status
    await session.flush()
    return TaskOut.model_validate(task)
