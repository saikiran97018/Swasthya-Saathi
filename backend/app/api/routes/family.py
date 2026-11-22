"""Family profiles: the people an account holder books care for."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Response

from app.core.errors import BadRequest, Conflict, NotFound
from app.core.security import get_current_user
from app.database.connection import get_session
from app.database.models import FamilyMember, User
from app.database.repositories.family import MAX_FAMILY_MEMBERS, FamilyRepository
from app.schemas.family import FamilyMemberIn, FamilyMemberOut, FamilyMemberUpdate
from app.database.repositories.users import UserRepository
from app.services.appointments import normalise_mobile
from app.services.vaccines import VaccinationService
from app.utils.language import is_supported
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/family", tags=["family"])


def _mobile(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    mobile = normalise_mobile(raw)
    if mobile is None:
        raise BadRequest("The mobile number must be a 10-digit Indian number starting with 6, 7, 8 or 9.", code="invalid_mobile")
    return mobile


def _birth(d):
    """A real date of birth: not in the future, not absurdly old."""
    if d is None:
        return None
    today = date.today()
    if d > today or d.year < today.year - 120:
        raise BadRequest("The date of birth must be a real date in the past.", code="invalid_birth_date")
    return d


def _language(code: str | None) -> str | None:
    if code is None or not code.strip():
        return None
    if not is_supported(code.strip().lower()):
        raise BadRequest(f"Unsupported language '{code}'.", code="unsupported_language")
    return code.strip().lower()


async def _owned(session: AsyncSession, user: User, member_id: uuid.UUID) -> FamilyMember:
    member = await FamilyRepository(session).get_owned(user.id, member_id)
    if member is None:
        raise NotFound("Family member not found", code="family_member_not_found")
    return member


@router.get("", response_model=list[FamilyMemberOut])
async def list_family(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> list[FamilyMemberOut]:
    return [FamilyMemberOut.model_validate(m) for m in await FamilyRepository(session).list(user.id)]


@router.post("", response_model=FamilyMemberOut, status_code=201)
async def add_member(body: FamilyMemberIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> FamilyMemberOut:
    repo = FamilyRepository(session)
    if await repo.count(user.id) >= MAX_FAMILY_MEMBERS:
        raise Conflict(f"You can save up to {MAX_FAMILY_MEMBERS} family members. Remove one first.", code="family_limit")
    member = await repo.add(
        user_id=user.id, name=body.name, relation=body.relation, birth_year=_birth(body.birth_date).year if body.birth_date else body.birth_year, birth_date=_birth(body.birth_date),
        gender=body.gender, mobile=_mobile(body.mobile), language=_language(body.language),
    )
    if member.birth_date:
        await VaccinationService(session).sync_reminders(user, member, await UserRepository(session).primary_language(user.id))
    return FamilyMemberOut.model_validate(member)


@router.patch("/{member_id}", response_model=FamilyMemberOut)
async def update_member(
    member_id: uuid.UUID, body: FamilyMemberUpdate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")
) -> FamilyMemberOut:
    member = await _owned(session, user, member_id)
    sent = body.model_fields_set  # only what the client actually sent; an explicit null clears an optional field
    if "name" in sent:
        if body.name is None:
            raise BadRequest("name cannot be empty", code="validation_error")
        member.name = body.name
    if "relation" in sent and body.relation is not None:
        member.relation = body.relation
    if "birth_year" in sent:
        member.birth_year = body.birth_year
    if "birth_date" in sent:
        member.birth_date = _birth(body.birth_date)
        if member.birth_date:
            member.birth_year = member.birth_date.year
        await session.flush()
        await VaccinationService(session).sync_reminders(user, member, await UserRepository(session).primary_language(user.id))
    if "gender" in sent:
        member.gender = body.gender
    if "mobile" in sent:
        member.mobile = _mobile(body.mobile)
    if "language" in sent:
        member.language = _language(body.language)
    await session.flush()
    return FamilyMemberOut.model_validate(member)


@router.delete("/{member_id}", status_code=204)
async def delete_member(member_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> Response:
    """Past appointments for this person stay (their name is stored on each); only the profile goes."""
    member = await _owned(session, user, member_id)
    await VaccinationService(session).cancel_reminders(member.id)
    await FamilyRepository(session).delete(member)
    return Response(status_code=204)
