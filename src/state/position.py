"""
Wizard position — the two-part cursor into the flattened stage sequence.

This module is intentionally pure: no database, no I/O, no side effects.
It contains the three primitives that both transition() and invalidate_after()
are built on:

    Position             — the cursor (stage name + optional stop index)
    flattened_sequence() — builds the full ordered stage list for a given stop count
    positions_after()    — returns every position downstream of a target
    next_position()      — the immediate next position in the sequence

Everything in transition.py that needs to reason about "what comes after X"
or "what is the next step" calls these functions rather than re-implementing
the ordering logic inline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.state.enums import (
    STOP_STAGES_IN_ORDER,
    TRIP_POST_STOP_STAGES,
    TRIP_PRE_STOP_STAGES,
    TripLevelStage,
)


@dataclass(frozen=True)
class Position:
    """
    A point in the flattened wizard sequence.

    Trip-level stage:  Position(stage="setup")           stop_index=None
    Stop-level stage:  Position(stage="activities",      stop_index=0)
                       Position(stage="activities",      stop_index=2)

    frozen=True makes Position hashable and immutable — safe to use as a
    dict key or set member, and equality comparison works out of the box
    by comparing both fields.
    """
    stage: str
    stop_index: Optional[int] = None

    @property
    def is_trip_level(self) -> bool:
        return self.stop_index is None

    @property
    def is_stop_level(self) -> bool:
        return self.stop_index is not None

    def __str__(self) -> str:
        if self.stop_index is None:
            return self.stage
        return f"{self.stage}[{self.stop_index}]"


# ── Sequence construction ─────────────────────────────────────────────────────

def flattened_sequence(num_stops: int) -> list[Position]:
    """
    Build the complete ordered position list for a trip with `num_stops` cities.

    The result is the canonical navigation order:

        setup → country → city → flights → [intercity] → accommodation
          → activities[0] → activities[1] → … → daily_plan → final

    num_stops=0 (before the city stage is committed):
        [setup, country, city, flights, accommodation, daily_plan, final]

    num_stops=1 (single city — no intercity travel):
        [setup, country, city, flights, accommodation,
         activities[0], daily_plan, final]

    num_stops=3 (hub + two day-trips):
        [setup, country, city, flights, intercity, accommodation,
         activities[0], activities[1], activities[2], daily_plan, final]

    This function is the single place that encodes stage ordering. advance()
    and invalidate_after() derive their ordering from calling this function —
    never by duplicating the list manually.
    """
    sequence: list[Position] = []

    for stage in TRIP_PRE_STOP_STAGES:
        # Intercity travel only exists when there is somewhere to travel to.
        # A single-city trip has no hub-to-spoke leg, so the stage is absent
        # from the sequence rather than present-and-unreachable: an unvisited
        # commit row would claim the user skipped a decision that was never
        # offered. num_stops already determines the shape of the sequence, so
        # keying off it here keeps this a pure function of its one argument.
        if stage is TripLevelStage.intercity and num_stops < 2:
            continue
        sequence.append(Position(stage=stage.value))

    for stop_index in range(num_stops):
        for stage in STOP_STAGES_IN_ORDER:
            sequence.append(Position(stage=stage.value, stop_index=stop_index))

    for stage in TRIP_POST_STOP_STAGES:
        sequence.append(Position(stage=stage.value))

    return sequence


# ── Sequence queries ──────────────────────────────────────────────────────────

def positions_after(sequence: list[Position], target: Position) -> list[Position]:
    """
    Return every position that comes after `target` in `sequence`.

    Used by invalidate_after() to find the blast radius of a BACK action.

    Raises ValueError if target is not found in sequence — which would mean
    the trip's current_stage / current_stop_index is inconsistent with the
    number of stops on the trip.
    """
    try:
        idx = sequence.index(target)
    except ValueError:
        raise ValueError(
            f"Position {target} not found in sequence of length {len(sequence)}. "
            "This usually means trip.current_stage or current_stop_index is "
            "inconsistent with the number of stops on the trip."
        )
    return sequence[idx + 1:]


def next_position(sequence: list[Position], current: Position) -> Optional[Position]:
    """
    Return the position immediately after `current` in `sequence`.

    Returns None if `current` is the last position (i.e. we are already at
    `final` — the wizard is complete).

    This is what advance() calls. The loop-seam logic (stop N's activities
    lead to stop N+1's activities, the last stop's activities lead to
    daily_plan) is already embedded in the sequence order returned by
    flattened_sequence(), so advance() needs no special-casing — it just
    takes the next element.
    """
    after = positions_after(sequence, current)
    return after[0] if after else None