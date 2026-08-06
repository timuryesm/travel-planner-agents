"""
Database engine, session factory, and declarative Base.

Set DATABASE_URL in .env as:
    DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/travel_planner

The asyncpg driver is used for the running application.
Alembic uses a psycopg2 connection (see alembic/env.py).
"""
from __future__ import annotations

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


# ── Engine ────────────────────────────────────────────────────────────────────

def _normalize_async_url(raw: str) -> str:
    """
    Ensure the URL names the asyncpg driver.

    Managed Postgres providers (Railway, Render, Heroku) hand out URLs
    starting `postgresql://` or the legacy `postgres://`, with no driver.
    SQLAlchemy then loads the default sync driver and create_async_engine
    fails at import — before any handler runs, so the whole app dies at boot
    rather than degrading.

    Rewritten here rather than requiring the deployment to paste a doctored
    URL, because the provider's value is a reference (${{Postgres.DATABASE_URL}})
    that updates itself if the database is recreated. Hand-editing it would
    break that.

    A URL that already names a driver is left alone: `postgresql+asyncpg://`
    passes through untouched, and so would a deliberate choice of another one.
    """
    if raw.startswith("postgres://"):          # legacy Heroku-style scheme
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = "postgresql+asyncpg://" + raw[len("postgresql://"):]
    return raw


DATABASE_URL: str = _normalize_async_url(os.environ["DATABASE_URL"])

engine = create_async_engine(
    DATABASE_URL,
    echo=False,       # flip to True locally for SQL tracing
    future=True,
    pool_size=5,
    max_overflow=10,
)

# ── Session factory ───────────────────────────────────────────────────────────

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # objects remain usable after commit
)


# ── Declarative Base ──────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield one session per request.
    Commits on clean exit, rolls back on exception.

    Usage in a route:
        async def my_route(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise