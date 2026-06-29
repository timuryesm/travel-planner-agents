"""
Wizard transition — the single chokepoint for all state-machine navigation.

All wizard movement — committing a stage, skipping, stepping forward without
choosing, or jumping backward — routes through transition(). Nothing mutates
the wizard position or any commit row anywhere else in the codebase.

This single-chokepoint discipline means that forward gates, blast-radius
warnings, and future smart-invalidation (spec section 6, reversible) are all
one-place edits rather than hunts across the call graph.

DB dependency:
    transition() calls create_stops() and delete_stops() from
    src.db.trip_repository (Step 3). The file will import-error until
    trip_repository.py is in place; all other logic is complete.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Stop, StopStageCommit, Trip, TripStageCommit
from src.db.trip_repository import create_stops, delete_stops  # implemented in Step 3
from src.state.enums import CommitType, TripLevelStage, TripStatus
from src.state.position import (
    Position,
    flattened_sequence,
    next_position,
    positions_after,
)
from src.state.schemas import DestinationCommitData


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    Reconciliation will flag this as a gap if NAG_BOTH or NAG_GAPS_ONLY policy applies.
    """
    action: Literal["FORWARD"] = "FORWARD"


class BackAction(BaseModel):
    """
    User jumped back to a previous stage.

    All commits after target are cascade-invalidated to unvisited.
    If the target is setup or destination, all Stop rows are deleted
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

        # Setup commit: sync the multi_city denorm on the trip row so list
        # views don't need to parse JSONB to answer "is this multi-city?".
        if current.stage == TripLevelStage.setup.value:
            trip.multi_city = bool(action.data.get("multi_city", False))

        # Destination commit: the committed city list determines how many
        # stops exist. Delete any prior stops, then create new ones.
        # The sequence must be rebuilt afterward because its length changed.
        if current.stage == TripLevelStage.destination.value:
            dest_data = DestinationCommitData.model_validate(action.data)
            await delete_stops(trip, db)
            await create_stops(trip, dest_data.destinations, db)
            sequence = flattened_sequence(len(trip.stops))

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

    trip.updated_at = _utcnow()
    await db.flush()


# ── Private helpers ───────────────────────────────────────────────────────────

def _advance(trip: Trip, sequence: list[Position], current: Position) -> None:
    """
    Move the wizard cursor one step forward.

    Delegates all loop-seam logic to next_position(): the step from a
    stop's last stage to the next stop's first stage, and from the final
    stop's last stage to reconciliation, are already embedded in the
    sequence order. No special-casing is needed here.

    If current is the last position (final), nothing happens — the wizard
    is already complete.
    """
    nxt = next_position(sequence, current)
    if nxt is not None:
        trip.current_stage = nxt.stage
        trip.current_stop_index = nxt.stop_index

        # Mirror TripStatus when entering specific stages.
        if nxt.stage == TripLevelStage.reconciliation.value:
            trip.status = TripStatus.reconciling.value
        elif nxt.stage == TripLevelStage.final.value:
            trip.status = TripStatus.complete.value


async def _invalidate_after(
    trip: Trip,
    sequence: list[Position],
    target: Position,
    db: AsyncSession,
) -> None:
    """
    Reset every position after `target` to unvisited.

    Two paths depending on whether we're jumping before the stop block:

    Path A — target is a trip-level stage AND stops exist downstream:
        This means the user went back to setup or destination.
        Deleting the Stop rows via delete_stops() automatically cascades to
        their StopStageCommit rows, so we only need to reset the
        downstream trip-level commits (destination, reconciliation, final).

    Path B — target is within the stop block (or past it):
        No stops are deleted. Every downstream commit row is reset
        individually, whether it belongs to a stop or to the trip.
    """
    downstream = positions_after(sequence, target)

    stop_positions  = [p for p in downstream if p.is_stop_level]
    trip_positions  = [p for p in downstream if p.is_trip_level]

    # Path A: target is setup or destination — the whole stop block is downstream.
    if stop_positions and target.is_trip_level:
        if trip.stops:
            await delete_stops(trip, db)
        # Only trip-level commits remain after the stops are gone.
        for pos in trip_positions:
            _reset_commit(_find_trip_commit(trip, pos.stage))
        return

    # Path B: target is inside or after the stop block.
    for pos in stop_positions:
        _reset_commit(_find_stop_commit(trip, pos.stage, pos.stop_index))
    for pos in trip_positions:
        _reset_commit(_find_trip_commit(trip, pos.stage))


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
        "Was the trip loaded with trip_stage_commits eagerly?"
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