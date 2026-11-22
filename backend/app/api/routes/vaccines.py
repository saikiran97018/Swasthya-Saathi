"""Child vaccination tracker: the schedule for a family member, and marking a visit as done."""
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequest, NotFound
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import FamilyMember, User
from app.database.repositories.family import FamilyRepository
from app.database.repositories.users import UserRepository
from app.services import vaccines as vx

router = APIRouter(tags=["vaccines"])


class VaccineItem(BaseModel):
    key: str
    label: str
    vaccines: list[str]
    due_on: date
    status: str  # given | overdue | due | upcoming
    given_on: date | None = None
    note: str = ""


class VaccinationOut(BaseModel):
    member_id: uuid.UUID
    name: str
    birth_date: date | None
    eligible: bool
    reason: str | None = None  # no_birth_date | too_old
    schedule_name: str = vx.SCHEDULE_NAME
    disclaimer: str = vx.DISCLAIMER
    items: list[VaccineItem] = []


class MarkIn(BaseModel):
    given_on: date | None = None  # null = take the tick off again


async def _member(session: AsyncSession, user: User, member_id: uuid.UUID) -> FamilyMember:
    m = await FamilyRepository(session).get_owned(user.id, member_id)
    if m is None:
        raise NotFound("Family member not found", code="family_member_not_found")
    return m


async def _view(session: AsyncSession, m: FamilyMember) -> VaccinationOut:
    today = datetime.now(vx.IST).date()
    base = dict(member_id=m.id, name=m.name, birth_date=m.birth_date)
    if m.birth_date is None:
        return VaccinationOut(**base, eligible=False, reason="no_birth_date")
    if not vx.eligible(m.birth_date, today):
        return VaccinationOut(**base, eligible=False, reason="too_old")
    return VaccinationOut(**base, eligible=True, items=[VaccineItem(**i) for i in vx.schedule(m.birth_date, today, await vx.VaccinationService(session).given(m.id))])


@router.get("/family/{member_id}/vaccinations", response_model=VaccinationOut)
async def get_schedule(member_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> VaccinationOut:
    return await _view(session, await _member(session, user, member_id))


@router.put("/family/{member_id}/vaccinations/{milestone}", response_model=VaccinationOut)
async def mark_visit(
    member_id: uuid.UUID, milestone: str, body: MarkIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")
) -> VaccinationOut:
    m = await _member(session, user, member_id)
    if milestone not in vx.KEYS:
        raise NotFound("No such vaccination visit", code="milestone_not_found")
    if m.birth_date is None:
        raise BadRequest("Add the child's date of birth first.", code="no_birth_date")
    today = datetime.now(vx.IST).date()
    if body.given_on is not None and (body.given_on > today or body.given_on < m.birth_date):
        raise BadRequest("The date must be between the child's birth date and today.", code="invalid_date")
    svc = vx.VaccinationService(session)
    await svc.mark(m, milestone, body.given_on)
    await svc.sync_reminders(user, m, await UserRepository(session).primary_language(user.id))
    return await _view(session, m)
