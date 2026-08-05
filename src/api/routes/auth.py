"""
Auth routes — /auth/register and /auth/login.

Schemas are defined in this file because they are used nowhere else.

Register:  POST /auth/register  JSON body → 201 + token
Login:     POST /auth/login     OAuth2 form → 200 + token

Login accepts OAuth2PasswordRequestForm (form-encoded username + password)
rather than a JSON body. This makes FastAPI's built-in Swagger UI "Authorize"
button work out of the box — the form sends username/password and receives a
bearer token that the docs UI then attaches to every subsequent request.
The `username` field is treated as the email address.

Both endpoints return the same AuthResponse shape so the frontend can handle
register and login with identical token-storage logic.
"""
from __future__ import annotations

import uuid
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.jwt import create_access_token
from src.auth.password import hash_password, verify_password
from src.db.base import get_db
from src.db.models import User
from src.config.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    # Optional so a deployment with no INVITE_CODE set (and every local clone)
    # keeps working with the same request body it always used.
    invite_code: str | None = None


class AuthResponse(BaseModel):
    """Returned by both /register and /login."""
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    email: str


# ── POST /auth/register ───────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """
    Create a new user account and return an access token.

    409 if the email is already registered.
    The password is hashed before storage — the plaintext is never persisted.
    """
    # Registration gate. Checked BEFORE the email lookup so a wrong code
    # cannot be used to probe which addresses are already registered.
    #
    # settings.INVITE_CODE empty means open registration — the default, so a
    # fresh clone works with no setup. Set it in any deployed environment: the
    # app spends real Anthropic credits per trip, and an open register endpoint
    # on a public URL is an open wallet.
    if settings.INVITE_CODE:
        supplied = (body.invite_code or "").strip()
        # compare_digest rather than == so the comparison time doesn't vary
        # with how many leading characters happen to match.
        if not secrets.compare_digest(supplied, settings.INVITE_CODE):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A valid invite code is required to create an account.",
            )
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.flush()   # writes the row; session commit happens in get_db()

    return AuthResponse(
        access_token=create_access_token(user.id, user.email),
        user_id=user.id,
        email=user.email,
    )


# ── POST /auth/login ──────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Log in and receive an access token",
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """
    Verify credentials and return an access token.

    Accepts application/x-www-form-urlencoded with fields:
        username — the user's email address
        password — the user's password

    Returns the same 401 for "email not found" and "wrong password" so that
    the response body does not reveal whether an email address is registered.
    """
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    # Evaluate verify_password even when user is None so that the response
    # time is constant and does not leak "no such user" via timing.
    password_ok = verify_password(
        form_data.password,
        user.hashed_password if user else hash_password("dummy"),
    )

    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthResponse(
        access_token=create_access_token(user.id, user.email),
        user_id=user.id,
        email=user.email,
    )