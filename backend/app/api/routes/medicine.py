"""Daily medicine reminders: list, add and stop. (The assistant uses the same service through its medicine_reminder tool.)"""
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest, Conflict, NotFound
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import User
from app.database.repositories.users import UserRepository
from app.services.medicine import MAX_DAYS, MAX_TIMES, MedicineError, MedicineService

router = APIRouter(tags=["medicine"])


class MedicineIn(BaseModel):
    label: str = Field(min_length=2, max_length=60, description="What to take, in the person's own words, e.g. 'BP tablet'")
    times: list[str] = Field(min_length=1, max_length=MAX_TIMES, description="24-hour times in IST, e.g. ['08:00', '20:00']")
    days: int = Field(default=30, ge=1, le=MAX_DAYS)


class MedicineOut(BaseModel):
    series: str
    label: str
    times: list[str]
    ends_on: str | None = None
    next_due: datetime | None = None


@router.get("/medicine-reminders", response_model=list[MedicineOut])
async def list_reminders(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> list[dict]:
    return await MedicineService(session).list(user.id)


@router.post("/medicine-reminders", response_model=MedicineOut, status_code=201)
async def add_reminder(body: MedicineIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> dict:
    language = await UserRepository(session).primary_language(user.id)
    svc = MedicineService(session)
    try:
        made = await svc.create(user, label=body.label, times=body.times, days=body.days, language=language)
    except MedicineError as exc:
        raise (Conflict if exc.code == "too_many_medicine_reminders" else BadRequest)(exc.message, code=exc.code) from exc
    return next((g for g in await svc.list(user.id) if g["series"] == made["series"]), {**made, "next_due": None})


@router.delete("/medicine-reminders/{series}", status_code=204)
async def stop_reminder(series: str, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> Response:
    if not await MedicineService(session).stop(user.id, series=series):
        raise NotFound("No such medicine reminder", code="medicine_reminder_not_found")
    return Response(status_code=204)
