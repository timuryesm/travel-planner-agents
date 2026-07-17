"""
Wizard transition — the single chokepoint for all state-machine navigation.

All wizard movement — committing a stage, skipping, stepping forward without
choosing, or jumping backward — routes through transition(). Nothing mutates
the wizard position or any commit row anywhere else in the codebase.

This single-chokepoint discipline means that forward gates, blast-radius
warnings, and future smart-invalidation (spec section 6, reversible) are all
one-place edits rather than hunts across the call graph.

Hub-and-spoke shape:
    setup → country → city → flights → [intercity] → accommodation
          → activities[0..N] → daily_plan → final

The city commit is the structural one: it creates the Stop rows, sets
Trip.multi_city, and creates or deletes the conditional intercity commit row.
The intercity commit is structural in a smaller way — it writes each spoke's
dates onto its Stop row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Stop, StopStageCommit, Trip, TripStageCommit
from src.db.trip_repository import (
    create_intercity_commit,
    create_stops,
    delete_intercity_commit,
    delete_stops,
)
from src.state.enums import CommitType, TripLevelStage, TripStatus
from src.state.position import (
    Position,
    flattened_sequence,
    next_position,
    positions_after,
)
from src.state.schemas import (
    CityCommitData,
    CountryCommitData,
    IntercityCommitData,
    IntercitySegment,
    SetupCommitData,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Stages whose commits determine what the Stop rows are. Going back to any of
# them means the city commit is about to be redone, so the stops must go.
_STOP_DEFINING_STAGES = {
    TripLevelStage.setup.value,
    TripLevelStage.country.value,
    TripLevelStage.city.value,
}


# ── Action models ─────────────────────────────────────────────────────────────
#
# Pydantic v2 discriminated union on the "action" literal field.
# The API route deserialises the request body into TransitionAction, then
# passes it straight to transition(). Type narrowing inside transition()
# uses isinstance() checks.

class CommitAction(BaseModel):
    """
    User chose or self-provided a value for the current stage.

    commit_type must be "chosen" or "self_provided".
    data is the stage-specific payload, pre-validated by the caller using
    the appropriate *CommitData schema from src.state.schemas.
    self_provided_text is populated only when commit_type == "self_provided".
    """
    action: Literal["COMMIT"] = "COMMIT"
    commit_type: CommitType
    data: dict[str, Any]
    self_provided_text: Optional[str] = None


class SkipAction(BaseModel):
    """User pressed Skip. Stage is marked completed=True with commit_type=skipped."""
    action: Literal["SKIP"] = "SKIP"


class ForwardAction(BaseModel):
    """
    User advanced without choosing. Current stage stays unvisited (completed=False).
    """
    action: Literal["FORWARD"] = "FORWARD"


class BackAction(BaseModel):
    """
    User jumped back to a previous stage.

    All commits after target are cascade-invalidated to unvisited.
    If the target is at or before the city stage, all Stop rows are deleted
    (and their StopStageCommit rows cascade automatically).
    """
    action: Literal["BACK"] = "BACK"
    target_stage: str
    target_stop_index: Optional[int] = None

    @property
    def target(self) -> Position:
        return Position(stage=self.target_stage, stop_index=self.target_stop_index)


# The union type used by the API route as the request body type.
TransitionAction = Annotated[
    CommitAction | SkipAction | ForwardAction | BackAction,
    Field(discriminator="action"),
]


# ── Public entry point ────────────────────────────────────────────────────────

async def transition(
    trip: Trip,
    action: TransitionAction,
    db: AsyncSession,
) -> None:
    """
    Apply `action` to `trip` and persist the result.

    Precondition: `trip` must be fully loaded — all trip_stage_commits,
    all stops, and all stop_stage_commits must be in the session. The
    repository's load_trip() guarantees this.

    Postcondition: trip.current_stage, trip.current_stop_index, and the
    relevant commit row(s) are updated in the session. The caller is
    responsible for committing the session.
    """
    num_stops = len(trip.stops)
    sequence = flattened_sequence(num_stops)
    current = Position(stage=trip.current_stage, stop_index=trip.current_stop_index)

    if isinstance(action, CommitAction):
        commit = _get_commit(trip, current)
        commit.commit_type = action.commit_type.value
        commit.commit_data = action.data
        commit.self_provided_text = action.self_provided_text
        commit.completed = True

        # City commit: the committed city list determines how many stops exist,
        # whether this is a multi-city trip, and whether the intercity stage
        # exists at all. Delete any prior stops, then create new ones. The
        # sequence must be rebuilt afterward because its length changed.
        if current.stage == TripLevelStage.city.value:
            await _apply_city_commit(trip, action.data, db)
            sequence = flattened_sequence(len(trip.stops))

        # Intercity commit: mirror each spoke's chosen dates onto its Stop row,
        # so the activities agent and the assembler can read dates from the stop
        # rather than reaching across into another stage's commit payload.
        elif current.stage == TripLevelStage.intercity.value:
            _apply_intercity_commit(trip, action.data)

        # Final commit: the assembled plan has been accepted. Status flips here,
        # not on arrival at the stage — entering `final` only means the user is
        # looking at the assemble screen, and a trip with no itinerary is not
        # complete.
        elif current.stage == TripLevelStage.final.value:
            trip.status = TripStatus.complete.value

        _advance(trip, sequence, current)

    elif isinstance(action, SkipAction):
        commit = _get_commit(trip, current)
        commit.commit_type = CommitType.skipped.value
        commit.commit_data = None
        commit.self_provided_text = None
        commit.completed = True
        _advance(trip, sequence, current)

    elif isinstance(action, ForwardAction):
        # Current stage stays unvisited — nothing to write to the commit row.
        _advance(trip, sequence, current)

    elif isinstance(action, BackAction):
        target = action.target
        await _invalidate_after(trip, sequence, target, db)
        trip.current_stage = target.stage
        trip.current_stop_index = target.stop_index
        # Going back from a committed final un-completes the trip.
        if trip.status == TripStatus.complete.value:
            trip.status = TripStatus.in_progress.value

    trip.updated_at = _utcnow()
    await db.flush()


# ── Structural commit handlers ────────────────────────────────────────────────

async def _apply_city_commit(
    trip: Trip, data: dict[str, Any], db: AsyncSession
) -> None:
    """
    Rebuild the stop block from a city commit.

    cities[0] is the hub — the city flown into, where the accommodation is, and
    where every day-trip starts and ends. cities[1..N] are spokes.

    The country comes from the country commit rather than from each city, and
    the trip window from the setup commit. Both are read here rather than
    carried in the city payload so there is one place each fact can disagree
    with itself: none.

    The intercity commit row is created or deleted to match the city count,
    mirroring create_stops / delete_stops. flattened_sequence() omits the
    intercity position below two stops independently, so the sequence and the
    commit rows stay in agreement by both deriving from the same city count
    rather than by consulting each other.
    """
    city_data = CityCommitData.model_validate(data)
    setup = _committed_setup(trip)
    country = _committed_country(trip)

    await delete_stops(trip, db)
    await create_stops(
        trip,
        city_data.cities,
        country,
        setup.departure_date,
        setup.return_date,
        db,
    )

    trip.multi_city = len(city_data.cities) > 1

    if trip.multi_city:
        await create_intercity_commit(trip, db)
    else:
        await delete_intercity_commit(trip, db)


def _apply_intercity_commit(trip: Trip, data: dict[str, Any]) -> None:
    """
    Write each spoke's chosen dates onto its Stop row.

    The hub's dates were set at stop creation from the setup commit and are not
    touched — you are based there for the whole trip.

    Validation is here rather than in the Pydantic schema because it needs the
    trip window, which lives in a different commit. A day-trip that leaves
    before you land, or is still away on the morning your flight home departs,
    is not a scheduling nuance — it is a plan that cannot happen.
    """
    intercity_data = IntercityCommitData.model_validate(data)
    setup = _committed_setup(trip)
    _validate_segments(trip, intercity_data.segments, setup)

    by_index = {s.stop_index: s for s in trip.stops}
    for seg in intercity_data.segments:
        stop = by_index[seg.stop_index]
        stop.start_date = seg.travel_date
        stop.end_date = seg.return_date
        stop.updated_at = _utcnow()


def _validate_segments(
    trip: Trip, segments: list[IntercitySegment], setup: SetupCommitData
) -> None:
    """Reject segments that name a stop that isn't there, or dates that can't happen."""
    valid_indexes = {s.stop_index for s in trip.stops if s.stop_index > 0}
    seen: set[int] = set()

    for seg in segments:
        if seg.stop_index not in valid_indexes:
            raise ValueError(
                f"Intercity segment names stop_index {seg.stop_index}, which is "
                f"not a spoke on this trip (spokes: {sorted(valid_indexes)})."
            )
        if seg.stop_index in seen:
            raise ValueError(
                f"Intercity segments contain stop_index {seg.stop_index} twice."
            )
        seen.add(seg.stop_index)

        if seg.travel_date > seg.return_date:
            raise ValueError(
                f"Intercity segment for {seg.city} returns "
                f"({seg.return_date}) before it departs ({seg.travel_date})."
            )
        if seg.travel_date < setup.departure_date:
            raise ValueError(
                f"Intercity segment for {seg.city} departs {seg.travel_date}, "
                f"before the trip starts ({setup.departure_date})."
            )
        if seg.return_date >= setup.return_date:
            raise ValueError(
                f"Intercity segment for {seg.city} returns {seg.return_date}, "
                f"on or after the flight home ({setup.return_date})."
            )


# ── Committed-state readers ───────────────────────────────────────────────────

def _committed_setup(trip: Trip) -> SetupCommitData:
    """
    The setup payload — dates, travelers, budget.

    Raises if setup was never committed. Unreachable through the UI (setup is
    the first stage and offers no skip or forward), so this is an assertion
    about internal consistency rather than a user-facing condition.
    """
    commit = _find_trip_commit(trip, TripLevelStage.setup.value)
    if not commit.commit_data:
        raise ValueError(
            f"Trip {trip.id} has no committed setup data. Every later stage "
            "needs the trip dates; the wizard should not be able to reach one."
        )
    return SetupCommitData.model_validate(commit.commit_data)


def _committed_country(trip: Trip) -> str:
    """
    The committed country name.

    Raises if country was never committed — same reasoning as _committed_setup.
    Country and city are structural: a trip with no destination has nothing to
    plan, so neither stage offers skip or forward.
    """
    commit = _find_trip_commit(trip, TripLevelStage.country.value)
    if not commit.commit_data:
        raise ValueError(
            f"Trip {trip.id} has no committed country. The city stage cannot "
            "create stops without one."
        )
    return CountryCommitData.model_validate(commit.commit_data).country.name


# ── Private helpers ───────────────────────────────────────────────────────────

def _advance(trip: Trip, sequence: list[Position], current: Position) -> None:
    """
    Move the wizard cursor one step forward.

    Delegates all loop-seam logic to next_position(): the step from one stop's
    activities to the next stop's, and from the last stop's activities to
    daily_plan, are already embedded in the sequence order. No special-casing
    is needed here.

    If current is the last position (final), nothing happens — the wizard is
    already at the end.
    """
    nxt = next_position(sequence, current)
    if nxt is not None:
        trip.current_stage = nxt.stage
        trip.current_stop_index = nxt.stop_index


async def _invalidate_after(
    trip: Trip,
    sequence: list[Position],
    target: Position,
    db: AsyncSession,
) -> None:
    """
    Reset every position after `target` to unvisited.

    Two paths, chosen by whether the target's commit is what defines the stops:

    Path A — target is setup, country, or city:
        The city commit that created the Stop rows is about to be redone, so
        the stops go. Deleting them cascades to their StopStageCommit rows.
        The intercity commit row is deleted rather than reset, because its
        existence is decided by the next city commit, not by this one.

    Path B — target is flights, intercity, accommodation, or a stop-level stage:
        The cities are unchanged. Every downstream commit resets in place.

    The distinction matters more than it looks. The old design could test
    `target.is_trip_level` and infer "before the stop block", because trip-level
    stages only existed at the two ends. Under hub-and-spoke, flights /
    intercity / accommodation are trip-level AND sit before the stop block, so
    that test would delete every city on the trip when the user went back to
    change a flight.
    """
    downstream = positions_after(sequence, target)

    stop_positions = [p for p in downstream if p.is_stop_level]
    trip_positions = [p for p in downstream if p.is_trip_level]

    # Path A: the stop block is about to be rebuilt from a new city commit.
    if target.is_trip_level and target.stage in _STOP_DEFINING_STAGES:
        if trip.stops:
            await delete_stops(trip, db)
        await delete_intercity_commit(trip, db)

        for pos in trip_positions:
            if pos.stage == TripLevelStage.intercity.value:
                continue  # deleted, not reset — there is no row to reset
            _reset_commit(_find_trip_commit(trip, pos.stage))
        return

    # Path B: cities stay; reset downstream commits in place.
    for pos in stop_positions:
        _reset_commit(_find_stop_commit(trip, pos.stage, pos.stop_index))

    for pos in trip_positions:
        _reset_commit(_find_trip_commit(trip, pos.stage))
        # A reset intercity commit means the spoke dates it wrote are no longer
        # a choice the user has made. Leaving them on the Stop rows would let
        # the assembler read dates the wizard says were never picked — the same
        # class of quiet wrongness that derived dates caused before.
        if pos.stage == TripLevelStage.intercity.value:
            _clear_spoke_dates(trip)


def _clear_spoke_dates(trip: Trip) -> None:
    """
    NULL out every spoke's dates. The hub keeps its own — they came from the
    setup commit at stop creation, not from the intercity stage.
    """
    for stop in trip.stops:
        if stop.stop_index == 0:
            continue
        stop.start_date = None
        stop.end_date = None
        stop.updated_at = _utcnow()


def _reset_commit(commit: TripStageCommit | StopStageCommit) -> None:
    """Revert a commit row to its initial unvisited state."""
    commit.commit_type = CommitType.unvisited.value
    commit.commit_data = None
    commit.self_provided_text = None
    commit.completed = False
    commit.updated_at = _utcnow()


def _get_commit(
    trip: Trip, pos: Position
) -> TripStageCommit | StopStageCommit:
    """Return the commit row for `pos` from the already-loaded trip."""
    if pos.is_trip_level:
        return _find_trip_commit(trip, pos.stage)
    return _find_stop_commit(trip, pos.stage, pos.stop_index)  # type: ignore[arg-type]


def _find_trip_commit(trip: Trip, stage: str) -> TripStageCommit:
    for c in trip.trip_stage_commits:
        if c.stage == stage:
            return c
    raise ValueError(
        f"TripStageCommit not found: stage={stage!r}, trip_id={trip.id}. "
        "Was the trip loaded with trip_stage_commits eagerly? Note that "
        "intercity has no row on single-city trips — by design."
    )


def _find_stop_commit(
    trip: Trip, stage: str, stop_index: int
) -> StopStageCommit:
    for stop in trip.stops:
        if stop.stop_index == stop_index:
            for c in stop.stop_stage_commits:
                if c.stage == stage:
                    return c
    raise ValueError(
        f"StopStageCommit not found: stage={stage!r}, stop_index={stop_index}, "
        f"trip_id={trip.id}. Was the trip loaded with stops and stop_stage_commits eagerly?"
    )