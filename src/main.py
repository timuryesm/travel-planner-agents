"""
FastAPI application entrypoint.

This file is wiring only — no business logic lives here.
Everything meaningful is in src/api/routes/, src/state/, and src/db/.

To run:
    uvicorn src.main:app --reload

Interactive API docs (once running):
    http://localhost:8000/docs      ← Swagger UI with Authorize button
    http://localhost:8000/redoc     ← ReDoc

Phase C note:
    CORS origins below allow the React dev server (localhost:3000 / 5173).
    Update ALLOWED_ORIGINS in .env before deploying to production.
"""
from __future__ import annotations

# Must run before any project import — src/auth/jwt.py and src/db/base.py
# both read required env vars (SECRET_KEY, DATABASE_URL) at module import
# time, not inside a function. If load_dotenv() runs after those imports,
# .env values won't be in os.environ yet and the KeyError below will fire
# even with a correctly filled-in .env file.
from dotenv import load_dotenv
load_dotenv()

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config.logging_config import configure_logging
from src.api.routes.auth import router as auth_router
from src.api.routes.trips import router as trips_router
from src.api.routes.stage_options import router as stage_options_router
from src.api.routes import weather


# ── Startup / shutdown ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Run Alembic migrations on every startup so the DB schema is always
    current without a separate deployment step.

    command.upgrade() is synchronous but fast (it only applies pending
    migrations, or no-ops if already at head), so calling it in the
    lifespan without an executor is acceptable.

    ORDER MATTERS: command.upgrade() imports alembic/env.py, which calls
    fileConfig(alembic.ini) and sets the root logger to WARN inside this
    process. configure_logging() must run *after* it, or alembic wins and
    every agent's logger.info() is silently dropped.
    """
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    configure_logging()  # ← must follow command.upgrade(); see docstring

    yield  # application runs here

    # Nothing to clean up on shutdown in v1.


# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Travel Planner Agents",
    description=(
        "Multi-agent AI travel planning with a stepwise wizard. "
        "Agents handle flights, hotels, weather, activities, and budget. "
        "A persistent wizard state machine lets users navigate, skip, and revise "
        "each planning stage across sessions."
    ),
    version="0.2.0",
    lifespan=lifespan,
)


# ── CORS ──────────────────────────────────────────────────────────────────────
# Reads a comma-separated list from ALLOWED_ORIGINS env var.
# Falls back to the two standard React dev server ports for local development.

_raw_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5173",
)
_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,   # required for Authorization header
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ───────────────────────────────────────────────────────────────────
# Prefixes (/auth, /trips) are already embedded in each router — do not add
# them again here or every route will be doubled.

app.include_router(auth_router)
app.include_router(trips_router)
app.include_router(stage_options_router)
app.include_router(weather.router)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"], summary="Liveness check")
async def health() -> dict[str, str]:
    """Returns 200 OK. Used by load balancers and deployment health checks."""
    return {"status": "ok"}