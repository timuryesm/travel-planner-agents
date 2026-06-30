"""
Trip repository — the async database layer.

All SQL lives here. transition() and the API routes call these functions;
neither touches the session directly.

Six functions in dependency order:

    create_trip    — new wizard session + 4 TripStageCommit rows
    load_trip      — full eager load (required before calling transition())
    list_trips     — lightweight list for the trips index route
    create_stops   — called by transition() after destination is committed
    delete_stops   — called by transition() on BACK to setup/destination
    save_commit    — explicit flush for a mutated commit row
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Stop, StopStageCommit, Trip, TripStageCommit
from src.state.enums import CommitType, StopLevelStage, TripLevelStage
from src.state.schemas import Destination


# ── create_trip ───────────────────────────────────────────────────────────────

async def create_trip(user_id: uuid.UUID, db: AsyncSession) -> Trip:
    """
    Insert a new Trip and its four TripStageCommit rows (all unvisited).

    Trip PKs are generated Python-side (uuid.uuid4), so trip.id is
    available immediately — no flush needed before creating the commits.

    The four commit rows are appended to trip.trip_stage_commits before
    flush, so that relationship is already loaded on the returned object.

    trip.stops is never touched here (a new trip has none yet), so it is
    reloaded via load_trip() after flush rather than left unloaded. This
    matters specifically in async SQLAlchemy: while trip is transient
    (pre-INSERT), a first touch of an unset relationship auto-initialises
    to an empty list with no DB query. But after flush() the object is
    persistent, and a first touch at that point instead triggers a real
    lazy-load SELECT — which crashes with MissingGreenlet if it happens
    outside an awaited call (e.g. from a plain sync serialiser function
    like _trip_detail()). Returning a load_trip()-loaded object sidesteps
    that footgun entirely by ensuring every relationship is already
    populated before the caller ever touches it.
    """
    trip = Trip(user_id=user_id)
    db.add(trip)

    for stage in TripLevelStage.ordered():
        commit = TripStageCommit(
            trip_id=trip.id,
            stage=stage.value,
            commit_type=CommitType.unvisited.value,
            completed=False,
        )
        trip.trip_stage_commits.append(commit)

    await db.flush()

    loaded = await load_trip(trip.id, db)
    assert loaded is not None  # just created — load_trip cannot return None here
    return loaded


# ── load_trip ─────────────────────────────────────────────────────────────────

async def load_trip(
    trip_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[Trip]:
    """
    Load a trip with all relationships eagerly fetched.

    Must be called before transition() — the state machine expects
    trip.trip_stage_commits, trip.stops, and trip.stops[*].stop_stage_commits
    to already be in the session so it can look up and mutate commit rows
    without issuing lazy SELECT calls (which would fail in async context).

    Returns None if no trip with that id exists.
    """
    result = await db.execute(
        select(Trip)
        .options(
            selectinload(Trip.trip_stage_commits),
            selectinload(Trip.stops).selectinload(Stop.stop_stage_commits),
        )
        .where(Trip.id == trip_id)
    )
    return result.scalar_one_or_none()


# ── list_trips ────────────────────────────────────────────────────────────────

async def list_trips(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> list[Trip]:
    """
    Return all trips for a user, newest first.

    Relationships are NOT eagerly loaded — the list route only needs
    scalar columns (id, status, current_stage, multi_city, created_at).
    """
    result = await db.execute(
        select(Trip)
        .where(Trip.user_id == user_id)
        .order_by(Trip.created_at.desc())
    )
    return list(result.scalars().all())


# ── create_stops ──────────────────────────────────────────────────────────────

async def create_stops(
    trip: Trip,
    destinations: list[Destination],
    db: AsyncSession,
) -> None:
    """
    Create one Stop + four StopStageCommit rows per destination.

    Called by transition() immediately after the destination commit is
    written. destinations comes from DestinationCommitData.destinations —
    an ordered list where index i maps to stop_index i.

    After this function returns:
        len(trip.stops) == len(destinations)
        every stop has four commits, all unvisited

    Appending to trip.stops and stop.stop_stage_commits via the ORM
    relationship is sufficient — SQLAlchemy adds objects to the session
    automatically on collection append.
    """
    for stop_index, dest in enumerate(destinations):
        stop = Stop(
            trip_id=trip.id,
            stop_index=stop_index,
            city=dest.city,
            country=dest.country,
        )
        trip.stops.append(stop)   # registers stop in session via relationship

        for stage in StopLevelStage.ordered():
            commit = StopStageCommit(
                stop_id=stop.id,  # uuid4 generated Python-side — available immediately
                stage=stage.value,
                commit_type=CommitType.unvisited.value,
                completed=False,
            )
            stop.stop_stage_commits.append(commit)

    await db.flush()


# ── delete_stops ──────────────────────────────────────────────────────────────

async def delete_stops(trip: Trip, db: AsyncSession) -> None:
    """
    Delete all Stop rows for the trip and clear the in-memory collection.

    StopStageCommit rows are cleaned up automatically: Stop.stop_stage_commits
    has cascade="all, delete-orphan", so SQLAlchemy deletes child commit rows
    when their parent stop is deleted.

    Precondition: trip must have been loaded via load_trip() so that all
    stops and their stop_stage_commits are already in the session. If they
    are not in session, SQLAlchemy would try to SELECT them before deleting,
    which would fail in async context with a lazy-load error.

    After this function returns:
        len(trip.stops) == 0
        all downstream stop_stage_commits rows are gone from the DB
    """
    for stop in list(trip.stops):
        await db.delete(stop)

    trip.stops.clear()   # keep in-memory state consistent with DB state
    await db.flush()


# ── save_commit ───────────────────────────────────────────────────────────────

async def save_commit(
    commit: TripStageCommit | StopStageCommit,
    db: AsyncSession,
) -> None:
    """
    Flush a mutated commit row to the database.

    When commit rows are loaded via load_trip(), SQLAlchemy tracks all
    attribute mutations automatically — db.add() is a no-op for objects
    already in the session. This function exists as an explicit escape hatch
    for code paths that mutate a commit row outside of transition() and need
    to flush without committing the full session.
    """
    db.add(commit)   # no-op if already tracked; ensures new objects are added
    await db.flush()