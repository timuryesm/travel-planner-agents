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
    """
    Stages that belong to the trip as a whole (not per-stop).

    The hub-and-spoke model is what makes this list long and the stop-level
    list short. One country, one hub city, optional day-trips out and back:

        - flights        one roundtrip, origin <-> hub. Not per-city.
        - accommodation  one stay, in the hub, for the whole period.
        - daily_plan     one plan across the whole trip, not one per city.

    intercity is conditional: it only exists when more than one city was
    committed, because with a single city there is nowhere to travel to.
    flattened_sequence() omits it when num_stops < 2 — see position.py.
    """
    setup = "setup"
    country = "country"
    city = "city"
    flights = "flights"
    intercity = "intercity"
    accommodation = "accommodation"
    daily_plan = "daily_plan"
    final = "final"

    @classmethod
    def ordered(cls) -> list[TripLevelStage]:
        """
        Fixed sequence order for navigation.

        Includes intercity unconditionally — this is the canonical order of
        every trip-level stage that *can* exist. Whether a given trip actually
        has an intercity stage is decided by flattened_sequence(num_stops).
        Callers that sort commit rows (see trips.py) want this full list.
        """
        return [
            cls.setup,
            cls.country,
            cls.city,
            cls.flights,
            cls.intercity,
            cls.accommodation,
            cls.daily_plan,
            cls.final,
        ]


class StopLevelStage(str, Enum):
    """
    Stages that repeat once per stop in the per-stop block.

    Only activities. Under hub-and-spoke, flights / accommodation / daily_plan
    all became trip-level (see TripLevelStage), so the per-stop block collapsed
    from four stages to one: for each city you visit, which things to do there.
    """
    activities = "activities"

    @classmethod
    def ordered(cls) -> list[StopLevelStage]:
        """Fixed sequence order within a single stop."""
        return [cls.activities]


class TripStatus(str, Enum):
    in_progress = "in_progress"
    complete = "complete"          # final plan has been assembled
    abandoned = "abandoned"        # user walked away


# ── Navigation helpers ────────────────────────────────────────────────────────
# These constants are used by advance() and invalidate_after() to determine
# which stages are "before" and "after" a given position without needing to
# know the total number of stops in advance.

TRIP_PRE_STOP_STAGES: list[TripLevelStage] = [
    TripLevelStage.setup,
    TripLevelStage.country,
    TripLevelStage.city,
    TripLevelStage.flights,
    TripLevelStage.intercity,
    TripLevelStage.accommodation,
]

TRIP_POST_STOP_STAGES: list[TripLevelStage] = [
    TripLevelStage.daily_plan,
    TripLevelStage.final,
]

STOP_STAGES_IN_ORDER: list[StopLevelStage] = StopLevelStage.ordered()