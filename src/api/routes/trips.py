"""
Trips routes — wizard session CRUD and the transition endpoint.

Four endpoints:
    POST  /trips                    create a new wizard session
    GET   /trips                    list the current user's trips (summaries)
    GET   /trips/{trip_id}          full trip state: position + all commits
    POST  /trips/{trip_id}/transition  apply COMMIT / SKIP / FORWARD / BACK

All endpoints require a valid Bearer token (get_current_user dependency).
Ownership is checked before loading commit data — a trip belonging to another
user returns 404 rather than 403 to avoid leaking that the UUID exists.

Response schemas are defined here because they are used nowhere else.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.jwt import get_current_user
from src.db.base import get_db
from src.db.models import StopStageCommit, Trip, TripStageCommit, User
from src.db.trip_repository import create_trip, list_trips, load_trip
from src.state.enums import StopLevelStage, TripLevelStage
from src.state.transition import (
    CommitValidationError,
    TransitionAction,
    transition,
)

router = APIRouter(prefix="/trips", tags=["trips"])

# Lookup tables for deterministic stage ordering in responses.
# The wizard spec mandates a fixed sequence; clients must receive commits
# in that order so they can render the stage list without re-sorting.
_TRIP_STAGE_ORDER = {s.value: i for i, s in enumerate(TripLevelStage.ordered())}
_STOP_STAGE_ORDER = {s.value: i for i, s in enumerate(StopLevelStage.ordered())}


# ── Response schemas ──────────────────────────────────────────────────────────

class CommitResponse(BaseModel):
    """The commit wrapper for a single stage — mirrors spec section 3."""
    stage: str
    commit_type: str
    commit_data: Optional[dict[str, Any]]
    self_provided_text: Optional[str]
    completed: bool


class StopResponse(BaseModel):
    """One city stop with its stage commits in stage order."""
    stop_index: int
    city: str
    country: str
    stage_commits: list[CommitResponse]


class TripSummaryResponse(BaseModel):
    """Lightweight trip row — no commits, no stops. Used in the list endpoint."""
    id: uuid.UUID
    status: str
    current_stage: str
    current_stop_index: Optional[int]
    multi_city: bool
    created_at: datetime
    updated_at: datetime


class TripDetailResponse(TripSummaryResponse):
    """Full wizard state — position, all trip-level commits, all stops."""
    trip_stage_commits: list[CommitResponse]
    stops: list[StopResponse]


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _commit(c: TripStageCommit | StopStageCommit) -> CommitResponse:
    return CommitResponse(
        stage=c.stage,
        commit_type=c.commit_type,
        commit_data=c.commit_data,
        self_provided_text=c.self_provided_text,
        completed=c.completed,
    )


def _trip_detail(trip: Trip) -> TripDetailResponse:
    """Serialise a fully-loaded Trip to TripDetailResponse.

    Commits are sorted by canonical stage order so the client always receives
    them in wizard sequence regardless of insertion order in the DB.
    """
    return TripDetailResponse(
        id=trip.id,
        status=trip.status,
        current_stage=trip.current_stage,
        current_stop_index=trip.current_stop_index,
        multi_city=trip.multi_city,
        created_at=trip.created_at,
        updated_at=trip.updated_at,
        trip_stage_commits=[
            _commit(c)
            for c in sorted(
                trip.trip_stage_commits,
                key=lambda c: _TRIP_STAGE_ORDER.get(c.stage, 99),
            )
        ],
        stops=[
            StopResponse(
                stop_index=s.stop_index,
                city=s.city,
                country=s.country,
                stage_commits=[
                    _commit(c)
                    for c in sorted(
                        s.stop_stage_commits,
                        key=lambda c: _STOP_STAGE_ORDER.get(c.stage, 99),
                    )
                ],
            )
            for s in sorted(trip.stops, key=lambda s: s.stop_index)
        ],
    )


def _trip_summary(trip: Trip) -> TripSummaryResponse:
    return TripSummaryResponse(
        id=trip.id,
        status=trip.status,
        current_stage=trip.current_stage,
        current_stop_index=trip.current_stop_index,
        multi_city=trip.multi_city,
        created_at=trip.created_at,
        updated_at=trip.updated_at,
    )


# ── Ownership guard ───────────────────────────────────────────────────────────

async def _owned_trip(
    trip_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> Trip:
    """
    Load a trip with all relationships and verify ownership.

    Returns 404 for both "not found" and "wrong owner" so the response does
    not reveal whether a UUID belongs to a different user.
    """
    trip = await load_trip(trip_id, db)
    if trip is None or trip.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found.",
        )
    return trip


# ── POST /trips ───────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=TripDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new wizard session",
)
async def create_trip_route(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripDetailResponse:
    """
    Create a Trip with one TripStageCommit row per trip-level stage, all
    unvisited. The wizard cursor starts at the setup stage.

    "Four" was the old multi-city model; hub-and-spoke has eight trip-level
    stages, and intercity only gets a row once a second city is committed.
    """
    trip = await create_trip(current_user.id, db)
    return _trip_detail(trip)


# ── GET /trips ────────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=list[TripSummaryResponse],
    summary="List all trips for the current user",
)
async def list_trips_route(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TripSummaryResponse]:
    """
    Return all trips for the current user, newest first.

    Commits and stops are omitted — use GET /trips/{id} for the full state.
    """
    trips = await list_trips(current_user.id, db)
    return [_trip_summary(t) for t in trips]


# ── GET /trips/{trip_id} ──────────────────────────────────────────────────────

@router.get(
    "/{trip_id}",
    response_model=TripDetailResponse,
    summary="Get the full wizard state for a trip",
)
async def get_trip_route(
    trip_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripDetailResponse:
    """
    Return the complete wizard state:
        - current position (current_stage + current_stop_index)
        - every trip-level commit in stage order
        - every stop with its stage commits (activities only, under hub-and-spoke)

    The frontend calls this after every transition to re-render the wizard.
    """
    trip = await _owned_trip(trip_id, current_user, db)
    return _trip_detail(trip)


# ── POST /trips/{trip_id}/transition ─────────────────────────────────────────

@router.post(
    "/{trip_id}/transition",
    response_model=TripDetailResponse,
    summary="Advance the wizard (COMMIT / SKIP / FORWARD / BACK)",
)
async def transition_route(
    trip_id: uuid.UUID,
    action: TransitionAction,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TripDetailResponse:
    """
    Apply one wizard action and return the updated trip state.

    Action shapes (discriminated on the "action" field):

        { "action": "COMMIT",  "commit_type": "chosen",
          "data": { ...stage-specific payload... } }

        { "action": "COMMIT",  "commit_type": "self_provided",
          "data": {},  "self_provided_text": "I've booked AC061" }

        { "action": "SKIP" }

        { "action": "FORWARD" }

        { "action": "BACK", "target_stage": "country",
          "target_stop_index": null }

        { "action": "BACK", "target_stage": "activities",
          "target_stop_index": 1 }

    The full trip is loaded before transition() is called — transition()
    requires all relationships to be in the session.
    After transition() flushes, the session is committed by get_db().

    A COMMIT whose payload doesn't match the current stage's schema returns 422
    with the offending fields. transition() validates against _COMMIT_SCHEMAS
    before it writes, so a rejected commit changes nothing — the trip is exactly
    as it was, and the user can fix the payload and try again.

    Only CommitValidationError becomes a 422. Other ValueErrors from
    transition() — a missing commit row, a stop that should exist and doesn't —
    are internal inconsistencies, not user input, and are left to surface as
    500s with a traceback. Catching ValueError here would merge the two, and
    since pydantic's ValidationError is itself a ValueError, it would report our
    bugs to the user as their mistake.
    """
    trip = await _owned_trip(trip_id, current_user, db)
    try:
        await transition(trip, action, db)
    except CommitValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=jsonable_encoder({"message": e.message, "errors": e.errors}),
        ) from e
    return _trip_detail(trip)