from __future__ import annotations
from enum import Enum


class CommitType(str, Enum):
    """
    The four states any stage commit can be in.

    chosen        — user picked from AI/API results
    self_provided — user wrote their own (e.g. "I've booked AC061")
    skipped       — user pressed Skip deliberately; respected, not an error
    unvisited     — never reached, or passed with FORWARD without choosing

    completed == True  for: chosen, self_provided, skipped
    completed == False for: unvisited
    The completed flag is what distinguishes a deliberate skip from a genuine gap.
    """
    chosen = "chosen"
    self_provided = "self_provided"
    skipped = "skipped"
    unvisited = "unvisited"

    @property
    def is_completed(self) -> bool:
        return self in (
            CommitType.chosen,
            CommitType.self_provided,
            CommitType.skipped,
        )


class TripLevelStage(str, Enum):
    """Stages that belong to the trip as a whole (not per-stop)."""
    setup = "setup"
    destination = "destination"
    reconciliation = "reconciliation"
    final = "final"

    @classmethod
    def ordered(cls) -> list[TripLevelStage]:
        """Fixed sequence order for navigation."""
        return [cls.setup, cls.destination, cls.reconciliation, cls.final]


class StopLevelStage(str, Enum):
    """Stages that repeat once per stop in the per-stop block."""
    flights = "flights"
    accommodation = "accommodation"
    activities = "activities"
    daily_plan = "daily_plan"

    @classmethod
    def ordered(cls) -> list[StopLevelStage]:
        """Fixed sequence order within a single stop."""
        return [cls.flights, cls.accommodation, cls.activities, cls.daily_plan]


class TripStatus(str, Enum):
    in_progress = "in_progress"
    reconciling = "reconciling"   # user is at the reconciliation stage
    complete = "complete"          # final plan has been assembled
    abandoned = "abandoned"        # user walked away


# ── Navigation helpers ────────────────────────────────────────────────────────
# These constants are used by advance() and invalidate_after() to determine
# which stages are "before" and "after" a given position without needing to
# know the total number of stops in advance.

TRIP_PRE_STOP_STAGES: list[TripLevelStage] = [
    TripLevelStage.setup,
    TripLevelStage.destination,
]

TRIP_POST_STOP_STAGES: list[TripLevelStage] = [
    TripLevelStage.reconciliation,
    TripLevelStage.final,
]

STOP_STAGES_IN_ORDER: list[StopLevelStage] = StopLevelStage.ordered()