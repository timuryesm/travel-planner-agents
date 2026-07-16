"""
Stage options route — the wizard's window into the Phase A agents.

    POST /trips/{trip_id}/stages/{stage}/options

Given a trip and a stage name, runs the matching agent against the trip's
committed context (setup dates/budget/origin + the target stop's city) and
returns a list of options shaped for that stage's frontend commit payload:

    destination   → [Destination]
    flights       → [FlightOption]
    accommodation → [HotelOption]
    activities    → [Activity]

Ownership is enforced the same way as the other trip routes: a trip belonging
to another user returns 404, not 403.

Why POST and not GET: running an agent can hit external APIs and is not
cacheable/idempotent in the HTTP sense. POST also leaves room to pass
stage-specific hints in the body later without reworking the signature.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.jwt import get_current_user
from src.db.base import get_db
from src.db.models import User
from src.db.trip_repository import load_trip
from src.agents.options_adapter import STAGE_FETCHERS

router = APIRouter(prefix="/trips", tags=["stage-options"])


class StageOptionsResponse(BaseModel):
    stage: str
    stop_index: Optional[int]
    city: Optional[str]
    options: list[dict[str, Any]]


# Stages that need a target city (everything except destination discovery)
_CITY_STAGES = {"flights", "accommodation", "activities"}


@router.post(
    "/{trip_id}/stages/{stage}/options",
    response_model=StageOptionsResponse,
    summary="Get agent-proposed options for a wizard stage",
)
async def get_stage_options(
    trip_id: uuid.UUID,
    stage: str,
    stop_index: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StageOptionsResponse:
    # Validate stage name
    fetcher = STAGE_FETCHERS.get(stage)
    if fetcher is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No options available for stage '{stage}'.",
        )

    # Load + ownership check
    trip = await load_trip(trip_id, db)
    if trip is None or trip.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found.",
        )

    # The setup commit holds the dates / budget / origin every agent needs
    setup_commit = next(
        (c for c in trip.trip_stage_commits if c.stage == "setup"), None
    )
    if not setup_commit or not setup_commit.commit_data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup must be completed before requesting options.",
        )
    setup = setup_commit.commit_data

    # Destination discovery needs no city; the others do
    if stage == "destination":
        options = await run_in_threadpool(destination_fetch, fetcher, setup)
        return StageOptionsResponse(
            stage=stage, stop_index=None, city=None, options=options
        )

    # City-based stages: resolve the target stop
    if stage in _CITY_STAGES:
        if stop_index is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"stop_index is required for stage '{stage}'.",
            )
        stop = next((s for s in trip.stops if s.stop_index == stop_index), None)
        if stop is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No stop at index {stop_index}.",
            )
        options = await run_in_threadpool(fetcher, setup, stop.city)
        return StageOptionsResponse(
            stage=stage, stop_index=stop_index, city=stop.city, options=options
        )

    # Should be unreachable given the STAGE_FETCHERS keys
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported stage '{stage}'.",
    )


def destination_fetch(fetcher, setup: dict) -> list[dict]:
    """destination_options takes only setup; wrapper keeps the call site clean."""
    return fetcher(setup)