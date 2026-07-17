"""
Stage options route — the wizard's window into the Phase A agents.

    POST /trips/{trip_id}/stages/{stage}/options

Given a trip and a stage name, runs the matching agent against the trip's
committed context and returns a list of options shaped for that stage's
frontend commit payload:

    country       → [Country]
    flights       → [FlightOption]
    accommodation → [HotelOption]
    activities    → [Activity]

Ownership is enforced the same way as the other trip routes: a trip belonging
to another user returns 404, not 403.

Why POST and not GET: running an agent can hit external APIs and is not
cacheable/idempotent in the HTTP sense. The body carries stage-specific hints
(exclude, preference_text, limit) which is what powers the regenerate and
expand buttons.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.options_adapter import STAGE_FETCHERS, OptionsContext
from src.auth.jwt import get_current_user
from src.db.base import get_db
from src.db.models import Trip, User
from src.db.trip_repository import load_trip
from src.state.enums import TripLevelStage
from src.state.schemas import CountryCommitData, SetupCommitData

router = APIRouter(prefix="/trips", tags=["stage-options"])


class StageOptionsRequest(BaseModel):
    """
    Stage-specific hints. All optional — an empty body is a valid first request.

    exclude carries names the user has already been shown. It is what makes
    "regenerate" produce a different list rather than a reshuffle of the same
    one, and "show more" extend rather than repeat.
    """
    stop_index: Optional[int] = None
    exclude: list[str] = Field(default_factory=list)
    preference_text: Optional[str] = None
    limit: Optional[int] = Field(default=None, ge=1, le=20)


class StageOptionsResponse(BaseModel):
    stage: str
    stop_index: Optional[int]
    city: Optional[str]
    options: list[dict[str, Any]]


# Stages needing the hub city — the city flown into, where the hotel is.
# Both are trip-level under hub-and-spoke: one flight, one hotel, per trip.
_HUB_STAGES = {"flights", "accommodation"}

# Stages targeting one stop. activities is the only stage that repeats per city.
_STOP_STAGES = {"activities"}


@router.post(
    "/{trip_id}/stages/{stage}/options",
    response_model=StageOptionsResponse,
    summary="Get agent-proposed options for a wizard stage",
)
async def get_stage_options(
    trip_id: uuid.UUID,
    stage: str,
    body: StageOptionsRequest = StageOptionsRequest(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StageOptionsResponse:
    fetcher = STAGE_FETCHERS.get(stage)
    if fetcher is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No options available for stage '{stage}'.",
        )

    trip = await load_trip(trip_id, db)
    if trip is None or trip.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found.",
        )

    ctx = _build_context(trip, stage, body)
    options = await run_in_threadpool(fetcher, ctx)

    return StageOptionsResponse(
        stage=stage,
        stop_index=body.stop_index if stage in _STOP_STAGES else None,
        city=ctx.target_city or ctx.hub_city,
        options=options,
    )


def _build_context(
    trip: Trip, stage: str, body: StageOptionsRequest
) -> OptionsContext:
    """
    Assemble everything the fetcher might need from the trip's committed state.

    Built here rather than in the adapter so the adapter never touches the ORM.
    Each stage's requirements are checked as they are read: asking for flights
    before a city exists is a 409, not an agent that quietly plans a trip to "".
    """
    setup_commit = next(
        (c for c in trip.trip_stage_commits if c.stage == TripLevelStage.setup.value),
        None,
    )
    if not setup_commit or not setup_commit.commit_data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup must be completed before requesting options.",
        )
    setup = SetupCommitData.model_validate(setup_commit.commit_data)

    ctx = OptionsContext(
        setup=setup,
        exclude=body.exclude,
        preference_text=body.preference_text,
        limit=body.limit,
    )

    # The committed country, if there is one. Present for every stage after
    # country; absent while the user is still choosing one.
    country_commit = next(
        (c for c in trip.trip_stage_commits if c.stage == TripLevelStage.country.value),
        None,
    )
    if country_commit and country_commit.commit_data:
        ctx.country = CountryCommitData.model_validate(
            country_commit.commit_data
        ).country.name

    # The hub is stops[0]; it exists once the city stage is committed.
    hub = next((s for s in trip.stops if s.stop_index == 0), None)
    if hub is not None:
        ctx.hub_city = hub.city

    if stage in _HUB_STAGES and ctx.hub_city is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A city must be chosen before requesting '{stage}' options.",
        )

    if stage in _STOP_STAGES:
        if body.stop_index is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"stop_index is required for stage '{stage}'.",
            )
        stop = next(
            (s for s in trip.stops if s.stop_index == body.stop_index), None
        )
        if stop is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No stop at index {body.stop_index}.",
            )
        ctx.target_city = stop.city
        # NULL for a spoke whose dates the intercity stage has not set yet.
        # Passed through as None rather than defaulted to the trip window —
        # an agent planning a day trip needs the day, and inventing one is how
        # every city ended up sharing a date range under the old design.
        ctx.target_start_date = stop.start_date
        ctx.target_end_date = stop.end_date

    return ctx