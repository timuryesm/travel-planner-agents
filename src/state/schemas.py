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
    Country, City, Citation, IntercityOption, Activity, FlightLeg,
    FlightOption, HotelOption and BudgetBreakdown are re-exported here so the
    rest of the codebase imports from one place.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Re-export the agent-result models unchanged — import from here, not from
# travel_plan. They live there because TravelPlan's own fields need them and
# this module already imports from it; defining them here and importing back
# would be circular.
from src.state.travel_plan import (  # noqa: F401
    DayPlan,
    Activity,
    BudgetBreakdown,
    Citation,
    City,
    Country,
    FlightLeg,
    FlightOption,
    HotelOption,
    IntercityOption,
)


# ── New models (spec section 4) ───────────────────────────────────────────────

class IntercitySegment(BaseModel):
    """
    One day-trip out from the hub and back.

    travel_date / return_date may be the same day. Both must fall strictly
    inside the trip window — you cannot leave before you have landed, and you
    cannot still be in Kyoto on the morning your flight home departs from Tokyo.
    The UI enforces the window; this schema records the result.

    stop_index points at the Stop row for this city, which is where these dates
    are mirrored when the commit lands.
    """
    stop_index: int = Field(ge=1)   # 0 is the hub — you don't day-trip to it
    city: str
    travel_date: date
    return_date: date
    selected: IntercityOption


# ── Per-stage commit_data payload schemas ─────────────────────────────────────

class SetupCommitData(BaseModel):
    """
    Setup stage payload — the expanded TravelRequest for the wizard.

    origin is added beyond the spec's listed fields because every
    subsequent flight search needs a departure city.

    No multi_city: under hub-and-spoke the user does not declare a multi-city
    trip up front, they discover it by pressing "Add another city" at the city
    stage. Trip.multi_city is now derived from the city commit.
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
    language: str = "en"

class CountryCommitData(BaseModel):
    """
    Country stage payload — exactly one country per trip.

    Visiting a second country is a different plan, not a longer one: it needs
    its own flights, its own advisory, its own hub. That is what the Plans
    section is for.
    """
    country: Country


class CityCommitData(BaseModel):
    """
    City stage payload — the ordered city list, all within the committed country.

    cities[0] is the HUB: the city you fly into, where the accommodation is, and
    where every day-trip starts and ends. cities[1..N] are spokes.

    The list is ordered and cities[i] corresponds to Stop.stop_index == i. When
    this commit is saved the application creates one Stop row per city with its
    activities commit, sets Trip.multi_city from len(cities) > 1, and creates or
    deletes the intercity commit row to match.
    """
    cities: list[City] = Field(min_length=1)


class FlightsCommitData(BaseModel):
    """
    Flights stage — the single chosen FlightOption.

    One roundtrip, origin to hub and back, for the whole trip. Spoke cities are
    reached from the hub and are the intercity stage's business.
    """
    selected: FlightOption


class IntercityCommitData(BaseModel):
    """
    Intercity stage — how to reach each spoke city from the hub, and when.

    This stage only exists when more than one city was committed; the sequence
    omits it and no commit row is created for single-city trips.
    """
    segments: list[IntercitySegment] = Field(min_length=1)


class AccommodationCommitData(BaseModel):
    """
    Accommodation stage — the single chosen HotelOption, in the hub city.

    HotelOption.provider already encodes booking.com vs airbnb.

    check_in / check_out exist for the multi-city case, where the user may want
    to check out before the return flight rather than keep the room for nights
    spent elsewhere. Single-city trips set them to the trip dates. Overnight
    stays in spoke cities are out of scope for now — the agent offers a text
    suggestion about where to stay and books nothing.
    """
    selected: HotelOption
    check_in: date
    check_out: date


class ActivitiesCommitData(BaseModel):
    """
    Activities stage — the chosen activities for one city, in the user's order.

    Ordered, not a set: the user arranges their picks, and that order feeds the
    daily plan. min_length 0 — choosing nothing in a city is allowed.

    preference_text is what the user typed before the suggestions were
    generated. Kept so that revisiting the stage restores the box, and so
    assembly can see what they were going for.
    """
    chosen: list[Activity] = Field(min_length=0)
    preference_text: Optional[str] = None


class DailyPlanCommitData(BaseModel):
    """
    Daily-plan stage payload — one plan across the whole trip.

    Generated from chosen activities + trip dates + spoke dates, then
    potentially mutated by free-text chat edits. What's stored is the current
    (post-edit) version — the authoritative form for final assembly, which
    renders these days rather than re-deriving them.
    """
    day_by_day: list[DayPlan]


class FinalCommitData(BaseModel):
    """
    Final stage payload — the assembled plan.

    Data-bearing, unlike the old final stage, which was a position marker.
    POST /trips/{id}/assemble generates this; the user commits it through the
    normal transition path. Revisiting the stage then renders the saved plan
    instead of paying to regenerate it, and regeneration stays an explicit
    choice.
    """
    itinerary_markdown: str
    budget: BudgetBreakdown
    generated_at: datetime


# ── Union type for JSONB deserialisation ─────────────────────────────────────
# Useful for type checkers and generic deserialisation helpers.

StageCommitData = (
    SetupCommitData
    | CountryCommitData
    | CityCommitData
    | FlightsCommitData
    | IntercityCommitData
    | AccommodationCommitData
    | ActivitiesCommitData
    | DailyPlanCommitData
    | FinalCommitData
)