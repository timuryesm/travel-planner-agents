"""
JWT authentication — token creation, verification, and the FastAPI dependency.

Three responsibilities, kept in one file because they share the same secret
and algorithm constant and are always used together:

    create_access_token  — sign a token for a newly authenticated user
    decode_token         — verify signature + expiry, return raw payload
    get_current_user     — FastAPI Depends() that turns a Bearer token into a
                           User ORM object; raises 401 on any failure

All 401 errors use the same vague message ("Could not validate credentials")
so that an attacker cannot distinguish between "no such user", "wrong
password", and "expired token" from the response body.

Requires: python-jose[cryptography]
    pip install "python-jose[cryptography]"

Environment variables:
    SECRET_KEY  — long random string used to sign tokens; rotate to invalidate
                  all outstanding tokens immediately
                  Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.base import get_db
from src.db.models import User


# ── Configuration ─────────────────────────────────────────────────────────────

SECRET_KEY: str = os.environ["SECRET_KEY"]
ALGORITHM: str = "HS256"

# Token lifetime. 7 days is a reasonable default for a web/mobile wizard app
# where mid-trip interruption is expected. Shorten for stricter security.
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 7)
)

# Tells FastAPI's OAuth2 flow where the login endpoint lives.
# The OpenAPI /docs page uses this to show an "Authorize" button.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Reusable 401 exception — same message for every failure so attackers
# cannot distinguish between expired, tampered, or user-not-found tokens.
_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


# ── Token creation ────────────────────────────────────────────────────────────

def create_access_token(user_id: uuid.UUID, email: str) -> str:
    """
    Return a signed JWT for the given user.

    Payload claims:
        sub   — user UUID as string (JWT standard "subject" claim)
        email — stored in the token so routes can display it without a DB hit
        exp   — expiry timestamp (handled automatically by jose on decode)
        iat   — issued-at timestamp (informational)
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ── Token verification ────────────────────────────────────────────────────────

def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a JWT. Raises 401 on any failure.

    jose.decode() validates the signature and the exp claim in one call.
    A tampered token, an expired token, and a token signed with a different
    key all raise JWTError, which we convert to the same 401.
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise _CREDENTIALS_EXCEPTION


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_current_user(
    token: str = Depends(_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency: Bearer token → User ORM object.

    Inject with:  user: User = Depends(get_current_user)

    Flow:
        1. FastAPI extracts the Bearer token from the Authorization header.
        2. decode_token() verifies signature and expiry.
        3. We load the User row by the UUID in the `sub` claim.
        4. Any failure at steps 2–3 raises 401.

    The user row is loaded fresh on every request — if an account is deleted
    or disabled, the next request fails immediately rather than serving a
    cached value.
    """
    payload = decode_token(token)

    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        raise _CREDENTIALS_EXCEPTION

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise _CREDENTIALS_EXCEPTION

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise _CREDENTIALS_EXCEPTION

    return user