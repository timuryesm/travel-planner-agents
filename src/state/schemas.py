"""
Pydantic schemas for stage commit payloads.

These define what goes inside the JSONB commit_data column for each stage.
They are the schema registry that Postgres doesn't enforce — validation
happens here at the application boundary, on read and write.

Usage:
    # Writing a commit
    data = FlightsCommitData(selected=flight_option)
    commit.commit_data = data.model_dump(mode="json")

    # Reading a commit
    data = FlightsCommitData.model_validate(commit.commit_data)

Re-exports:
    FlightOption, FlightLeg, HotelOption, Activity are re-exported here
    so the rest of the codebase imports from one place.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Re-export existing models unchanged — import from here, not from travel_plan
from src.state.travel_plan import Activity, FlightLeg, FlightOption, HotelOption  # noqa: F401


# ── New models (spec section 4) ───────────────────────────────────────────────

class Destination(BaseModel):
    """One city in the destination commit."""
    city: str
    country: str
    why_chosen_summary: str
    season_note: str
    safety_note: str   # sourced from a live travel-advisory signal, not model memory


class DayPlan(BaseModel):
    """
    One day in a stop's daily plan.

    activity_names is an ordered list of Activity.name values from the
    same stop's activities commit. Loose string reference — not a FK —
    because all data lives in JSONB.

    This is the *mutated* form: free-text chat edits are applied here.
    What's stored is the current (potentially user-edited) version.
    """
    date: date
    weather_line: str               # e.g. "Sunny, 24 °C"
    activity_names: list[str]       # ordered, references Activity.name


# ── Per-stage commit_data payload schemas ─────────────────────────────────────

class SetupCommitData(BaseModel):
    """
    Setup stage payload — the expanded TravelRequest for the wizard.

    origin is added beyond the spec's listed fields because every
    subsequent flight search needs a departure city.

    multi_city is also written to Trip.multi_city (denorm) when this
    commit is saved, so list/detail views don't need to parse JSONB.
    """
    origin: str
    departure_date: date
    return_date: date
    num_travelers: int = Field(ge=1)
    travel_type: Literal["relax", "active", "hybrid"]
    budget_amount: Optional[float] = Field(default=None, ge=0)
    budget_currency: str = "USD"
    with_kids: bool = False
    preferences_text: Optional[str] = None
    multi_city: bool = False


class DestinationCommitData(BaseModel):
    """
    Destination stage payload.

    Always stored as a list — single-city trips get a list of one.
    The list is ordered: destinations[i] corresponds to Stop.stop_index == i.
    When this commit is saved, the application creates one Stop row per
    destination and initialises four StopStageCommit rows (all unvisited)
    for each stop.
    """
    destinations: list[Destination] = Field(min_length=1)


class FlightsCommitData(BaseModel):
    """Flights stage — the single chosen FlightOption."""
    selected: FlightOption


class AccommodationCommitData(BaseModel):
    """Accommodation stage — the single chosen HotelOption.
    HotelOption.provider already encodes booking.com vs airbnb."""
    selected: HotelOption


class ActivitiesCommitData(BaseModel):
    """Activities stage — the list of chosen Activities (not a single pick)."""
    chosen: list[Activity] = Field(min_length=0)


class DailyPlanCommitData(BaseModel):
    """
    Daily-plan stage payload.

    Generated from chosen activities + trip dates, then potentially
    mutated by free-text chat edits. What's stored is the current
    (post-edit) version — the authoritative form for final assembly.
    """
    day_by_day: list[DayPlan]


# ── Union type for JSONB deserialisation ─────────────────────────────────────
# Useful for type checkers and generic deserialisation helpers.

StageCommitData = (
    SetupCommitData
    | DestinationCommitData
    | FlightsCommitData
    | AccommodationCommitData
    | ActivitiesCommitData
    | DailyPlanCommitData
)