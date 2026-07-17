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

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Stop, StopStageCommit, Trip, TripStageCommit
from src.db.trip_repository import (
    create_intercity_commit,
    create_stops,
    delete_intercity_commit,
    delete_stops,
)
from src.state.enums import CommitType, StopLevelStage, TripLevelStage, TripStatus
from src.state.position import (
    Position,
    flattened_sequence,
    next_position,
    positions_after,
)
from src.state.schemas import (
    AccommodationCommitData,
    ActivitiesCommitData,
    CityCommitData,
    CountryCommitData,
    DailyPlanCommitData,
    FinalCommitData,
    FlightsCommitData,
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


class CommitValidationError(ValueError):
    """
    The payload the user sent is not valid for the stage they are on.

    A distinct type, and NOT plain ValueError, because the route has to tell
    two things apart that both surface as ValueError:

      - the user sent nonsense           → 422, their problem, fixable by them
      - _find_trip_commit found no row   → 500, our problem, a bug

    Pydantic's own ValidationError is a subclass of ValueError, so `except
    ValueError` in the route would sweep up internal-consistency failures and
    report them to the user as bad input. Wrapping the pydantic error in this
    type keeps the two populations separate.

    `errors` carries pydantic's per-field list when there is one, so the route
    can hand the frontend "departure_date: Field required" rather than a wall
    of text.
    """

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []


# Stage → the schema its commit_data must satisfy.
#
# This is the mapping schemas.py's docstring already promised ("validation
# happens here at the application boundary, on read and write") but that nobody
# had written down. Without it, validation on write happened only where a
# structural hook needed the parsed object anyway — city and intercity — and
# the other seven stages persisted whatever JSON arrived. Swagger's
# `{"additionalProp1": {}}` placeholder committed cleanly as a setup payload
# and then 500'd every options call on that trip, four stages downstream from
# the mistake.
#
# One entry per stage that carries data. Adding a stage without adding it here
# raises at commit time rather than failing silently — see _validate_commit_data.
_COMMIT_SCHEMAS: dict[str, type[BaseModel]] = {
    TripLevelStage.setup.value: SetupCommitData,
    TripLevelStage.country.value: CountryCommitData,
    TripLevelStage.city.value: CityCommitData,
    TripLevelStage.flights.value: FlightsCommitData,
    TripLevelStage.intercity.value: IntercityCommitData,
    TripLevelStage.accommodation.value: AccommodationCommitData,
    TripLevelStage.daily_plan.value: DailyPlanCommitData,
    TripLevelStage.final.value: FinalCommitData,
    StopLevelStage.activities.value: ActivitiesCommitData,
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

    commit_type must be "chosen" or "self_provided" — the other two CommitType
    values describe how a stage ENDED UP, not something a user can do. SKIP
    produces `skipped`; `unvisited` is the initial state. Committing with
    either would set completed=True on a row claiming to be incomplete, and the
    completed flag is exactly what distinguishes a deliberate skip from a gap.

    data is the stage-specific payload. It is validated against the schema for
    the CURRENT STAGE inside transition() — this model cannot do it, because
    the request body does not say which stage it is for and the answer lives on
    the trip. Everything that can be checked without that knowledge is checked
    here, so it surfaces as FastAPI's own 422 with no route code involved.

    self_provided_text carries the user's own words ("I've booked AC061") and
    is required for a self_provided commit: without it the commit is empty and
    still claims to be complete.
    """
    action: Literal["COMMIT"] = "COMMIT"
    commit_type: CommitType
    data: dict[str, Any]
    self_provided_text: Optional[str] = None

    @model_validator(mode="after")
    def _check_commit_type(self) -> "CommitAction":
        if self.commit_type not in (CommitType.chosen, CommitType.self_provided):
            raise ValueError(
                f"commit_type must be 'chosen' or 'self_provided' for a COMMIT, "
                f"not '{self.commit_type.value}'. Use SKIP to skip a stage."
            )
        if self.commit_type is CommitType.self_provided and not (
            self.self_provided_text or ""
        ).strip():
            raise ValueError(
                "self_provided_text is required when commit_type is "
                "'self_provided' — it is the whole content of the commit."
            )
        return self


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
        # Validate BEFORE touching anything. The old order assigned
        # commit_data first and let _apply_city_commit validate afterwards,
        # which meant a bad payload had already been written to the row by the
        # time it was rejected — and for the seven stages with no structural
        # hook, it was never rejected at all.
        validated = _validate_commit_data(current.stage, action)

        commit = _get_commit(trip, current)
        commit.commit_type = action.commit_type.value
        # Store the round-tripped model, not the raw dict: dates become ISO
        # strings, defaults are filled in, and unknown keys are dropped. What
        # lands in JSONB is then exactly what a later model_validate will read
        # back, rather than whatever shape the client happened to send.
        commit.commit_data = (
            validated.model_dump(mode="json") if validated is not None else action.data
        )
        commit.self_provided_text = action.self_provided_text
        commit.completed = True

        # City commit: the committed city list determines how many stops exist,
        # whether this is a multi-city trip, and whether the intercity stage
        # exists at all. Delete any prior stops, then create new ones. The
        # sequence must be rebuilt afterward because its length changed.
        if current.stage == TripLevelStage.city.value and validated is not None:
            await _apply_city_commit(trip, validated, db)  # type: ignore[arg-type]
            sequence = flattened_sequence(len(trip.stops))

        # Intercity commit: mirror each spoke's chosen dates onto its Stop row,
        # so the activities agent and the assembler can read dates from the stop
        # rather than reaching across into another stage's commit payload.
        elif current.stage == TripLevelStage.intercity.value and validated is not None:
            _apply_intercity_commit(trip, validated)  # type: ignore[arg-type]

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


# ── Commit payload validation ─────────────────────────────────────────────────

def _validate_commit_data(stage: str, action: CommitAction) -> Optional[BaseModel]:
    """
    Check the payload against the schema for `stage`. Returns the parsed model,
    or None when there is nothing to parse.

    None for a self_provided commit: its content is self_provided_text, and
    `data` is {} by design. Validating {} against SetupCommitData would reject
    a perfectly legitimate "I've booked it myself".

    Raises CommitValidationError for a chosen commit whose data doesn't fit —
    which the route turns into a 422 with the per-field list. It is the user's
    input that is wrong, and they can see exactly which part.

    A stage missing from _COMMIT_SCHEMAS raises too, deliberately loudly: a new
    stage that nobody registered would otherwise inherit exactly the silent
    pass-through this function exists to remove.
    """
    if action.commit_type is CommitType.self_provided:
        return None

    schema = _COMMIT_SCHEMAS.get(stage)
    if schema is None:
        raise ValueError(
            f"No commit schema registered for stage '{stage}'. Add it to "
            f"_COMMIT_SCHEMAS in transition.py — every stage that carries data "
            f"must declare what that data is."
        )

    try:
        return schema.model_validate(action.data)
    except ValidationError as e:
        raise CommitValidationError(
            f"Invalid commit payload for stage '{stage}'.",
            errors=e.errors(include_url=False),
        ) from e


# ── Structural commit handlers ────────────────────────────────────────────────

async def _apply_city_commit(
    trip: Trip, city_data: CityCommitData, db: AsyncSession
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

    Takes the parsed CityCommitData rather than the raw dict: transition()
    validates every payload against _COMMIT_SCHEMAS before calling this, so
    re-validating here would parse the same JSON twice and imply this hook is
    the thing standing between bad input and the database. It isn't, any more.
    """
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


def _apply_intercity_commit(trip: Trip, intercity_data: IntercityCommitData) -> None:
    """
    Write each spoke's chosen dates onto its Stop row.

    The hub's dates were set at stop creation from the setup commit and are not
    touched — you are based there for the whole trip.

    Shape validation happens in transition() against _COMMIT_SCHEMAS, so this
    receives a parsed model. What stays here is the validation Pydantic cannot
    do: _validate_segments needs the trip window, which lives in a different
    commit. A day-trip that leaves before you land, or is still away on the
    morning your flight home departs, is not a scheduling nuance — it is a plan
    that cannot happen.
    """
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
    """
    Reject segments that name a stop that isn't there, or dates that can't happen.

    CommitValidationError, not ValueError: every failure here is the user's
    payload disagreeing with their own trip window, so it belongs in the 422
    population rather than the 500 one.
    """
    valid_indexes = {s.stop_index for s in trip.stops if s.stop_index > 0}
    seen: set[int] = set()

    for seg in segments:
        if seg.stop_index not in valid_indexes:
            raise CommitValidationError(
                f"Intercity segment names stop_index {seg.stop_index}, which is "
                f"not a spoke on this trip (spokes: {sorted(valid_indexes)})."
            )
        if seg.stop_index in seen:
            raise CommitValidationError(
                f"Intercity segments contain stop_index {seg.stop_index} twice."
            )
        seen.add(seg.stop_index)

        if seg.travel_date > seg.return_date:
            raise CommitValidationError(
                f"Intercity segment for {seg.city} returns "
                f"({seg.return_date}) before it departs ({seg.travel_date})."
            )
        if seg.travel_date < setup.departure_date:
            raise CommitValidationError(
                f"Intercity segment for {seg.city} departs {seg.travel_date}, "
                f"before the trip starts ({setup.departure_date})."
            )
        if seg.return_date >= setup.return_date:
            raise CommitValidationError(
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