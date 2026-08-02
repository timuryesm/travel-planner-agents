"""
Trip repository — the async database layer.

All SQL lives here. transition() and the API routes call these functions;
neither touches the session directly.

Eight functions in dependency order:

    create_trip              — new wizard session + 7 TripStageCommit rows
    load_trip                — full eager load (required before calling transition())
    list_trips               — lightweight list for the trips index route
    create_stops             — called by transition() after the city commit
    delete_stops             — called by transition() on BACK to setup/country/city
    create_intercity_commit  — called by transition() when >1 city is committed
    delete_intercity_commit  — called by transition() when the trip drops to 1 city
    save_commit              — explicit flush for a mutated commit row
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Stop, StopStageCommit, Trip, TripStageCommit
from src.state.enums import CommitType, StopLevelStage, TripLevelStage
from src.state.schemas import City


# ── create_trip ───────────────────────────────────────────────────────────────

async def create_trip(user_id: uuid.UUID, db: AsyncSession) -> Trip:
    """
    Insert a new Trip and its seven TripStageCommit rows (all unvisited).

    Seven, not eight: intercity is deliberately omitted. It only exists once
    more than one city has been committed, and the city commit creates it then
    (see create_intercity_commit). Seeding it here would leave every
    single-city trip carrying a permanently-unvisited row — and unvisited means
    "never reached", which would be a lie about a stage that was never offered.
    The sidebar reads commit rows to draw the stage list, so the lie would be
    visible: a step the user can neither complete nor get rid of.

    Trip PKs are generated Python-side (uuid.uuid4), so trip.id is
    available immediately — no flush needed before creating the commits.

    The commit rows are appended to trip.trip_stage_commits before
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
        if stage is TripLevelStage.intercity:
            continue  # created by the city commit, only when there are spokes
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
        .options(selectinload(Trip.stops))
        .order_by(Trip.created_at.desc())
    )
    return list(result.scalars().all())


# ── create_stops ──────────────────────────────────────────────────────────────

async def create_stops(
    trip: Trip,
    cities: list[City],
    country: str,
    departure_date: date,
    return_date: date,
    db: AsyncSession,
) -> None:
    """
    Create one Stop + its StopStageCommit rows per city.

    Called by transition() immediately after the city commit is written.
    cities comes from CityCommitData.cities — an ordered list where index i
    maps to stop_index i, and index 0 is the HUB.

    country is passed separately rather than read off each city because there
    is exactly one country per trip (it was chosen at the country stage). If
    every City object carried its own copy, two of them could disagree.

    Dates follow the hub-and-spoke model:

        hub (index 0)  — the setup dates. You fly in, you fly out, and you are
                         based there for the whole trip.
        spokes (1..N)  — NULL. The user picks each day-trip's dates at the
                         intercity stage, which has not run yet.

    NULL is the honest value here: "not chosen yet", not "same as the trip".
    The previous design had no per-stop dates at all and derived them from the
    trip, which is why every city in a multi-city trip silently shared one date
    range.

    After this function returns:
        len(trip.stops) == len(cities)
        every stop has one activities commit, unvisited
        stop 0 has dates; stops 1..N do not

    Appending to trip.stops and stop.stop_stage_commits via the ORM
    relationship is sufficient — SQLAlchemy adds objects to the session
    automatically on collection append.
    """
    for stop_index, c in enumerate(cities):
        is_hub = stop_index == 0
        stop = Stop(
            trip_id=trip.id,
            stop_index=stop_index,
            city=c.city,
            country=country,
            start_date=departure_date if is_hub else None,
            end_date=return_date if is_hub else None,
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


# ── create_intercity_commit ───────────────────────────────────────────────────

async def create_intercity_commit(trip: Trip, db: AsyncSession) -> None:
    """
    Add the trip's intercity TripStageCommit row if it does not already exist.

    Called by transition() when the city commit lands with more than one city.
    The stage is conditional on the trip's shape — with a single city there is
    no hub-to-spoke leg to plan — so its commit row is created and destroyed
    alongside the stops, rather than seeded at trip creation like the other
    seven. This mirrors create_stops / delete_stops exactly.

    flattened_sequence() independently omits the intercity position below two
    stops, so the sequence and the commit rows agree without either consulting
    the other: both derive from the same fact, the number of cities.

    Idempotent — safe to call when the row already exists (e.g. the user adds a
    third city to a trip that already had two).
    """
    existing = next(
        (
            c for c in trip.trip_stage_commits
            if c.stage == TripLevelStage.intercity.value
        ),
        None,
    )
    if existing is not None:
        return

    commit = TripStageCommit(
        trip_id=trip.id,
        stage=TripLevelStage.intercity.value,
        commit_type=CommitType.unvisited.value,
        completed=False,
    )
    trip.trip_stage_commits.append(commit)
    await db.flush()


# ── delete_intercity_commit ───────────────────────────────────────────────────

async def delete_intercity_commit(trip: Trip, db: AsyncSession) -> None:
    """
    Remove the trip's intercity TripStageCommit row if present.

    Called by transition() when the city commit lands with exactly one city —
    including when a user goes back and removes cities from a multi-city trip.
    Leaving the row behind would put a stage in the sidebar that the sequence
    no longer contains, and _find_trip_commit() would happily return a commit
    for a position that cannot be reached.

    Idempotent — safe to call when there is no row (the common single-city case).
    """
    existing = next(
        (
            c for c in trip.trip_stage_commits
            if c.stage == TripLevelStage.intercity.value
        ),
        None,
    )
    if existing is None:
        return

    await db.delete(existing)
    trip.trip_stage_commits.remove(existing)   # keep in-memory state consistent
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

async def delete_trip(trip: Trip, db: AsyncSession) -> None:
    """
    Delete a trip and everything under it.
 
    The schema cascade-deletes on every FK, so removing the Trip row takes its
    stops, all commit rows, and the saved itinerary with it. Irreversible —
    ownership is the route's job; this just executes.
    """
    await db.delete(trip)
    await db.commit()