"""Authentication. Guests get a real account + JWT instantly; they can later register to keep it."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Unauthorized
from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.database.connection import get_session
from app.database.models import User
from app.database.repositories.users import UserRepository
from app.schemas.misc import GuestIn, LoginIn, ProfileUpdate, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _token(user: User) -> TokenOut:
    return TokenOut(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.post("/guest", response_model=TokenOut, status_code=201)
async def guest(body: GuestIn | None = None, session: AsyncSession = Depends(get_session, scope="function")) -> TokenOut:
    user = await UserRepository(session).create(display_name=(body.display_name if body and body.display_name else "Guest"), is_guest=True)
    return _token(user)


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(body: RegisterIn, session: AsyncSession = Depends(get_session, scope="function")) -> TokenOut:
    repo = UserRepository(session)
    if await repo.get_by_email(body.email):
        raise Conflict("An account with this email already exists", code="email_taken")
    user = await repo.create(
        display_name=body.display_name or body.email.split("@")[0], email=body.email.lower(), password_hash=hash_password(body.password)
    )
    return _token(user)


@router.post("/upgrade", response_model=TokenOut)
async def upgrade_guest(body: RegisterIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> TokenOut:
    """Turn the current guest into a full account, keeping all conversations."""
    repo = UserRepository(session)
    existing = await repo.get_by_email(body.email)
    if existing and existing.id != user.id:
        raise Conflict("An account with this email already exists", code="email_taken")
    user.email, user.password_hash, user.is_guest = body.email.lower(), hash_password(body.password), False
    if body.display_name:
        user.display_name = body.display_name
    await session.flush()
    return _token(user)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session, scope="function")) -> TokenOut:
    user = await UserRepository(session).get_by_email(body.email)
    # same error for unknown email and wrong password: don't reveal which accounts exist
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise Unauthorized("Incorrect email or password", code="invalid_credentials")
    return _token(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me", response_model=UserOut)
async def update_me(body: ProfileUpdate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session, scope="function")) -> User:
    user.display_name = body.display_name.strip()
    await session.flush()
    return user
