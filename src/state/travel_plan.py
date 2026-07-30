from __future__ import annotations
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


# ── Inputs ──────────────────────────────────────────────────────────────────

class TravelRequest(BaseModel):
    """What the user asks for. Filled at the start, never mutated."""
    destination: str
    origin: str
    departure_date: date
    return_date: date
    budget_usd: float
    travelers: int = 1
    interests: list[str] = Field(default_factory=list)
    trip_type: str = "roundtrip"
    intermediate_stops: list[str] = Field(default_factory=list)
    accommodation_type: str = "any"
    # "any" | "hotel" | "apartment" | "hostel" | "villa" | "resort" | "guesthouse"
    accommodation_providers: list[str] = Field(default_factory=lambda: ["booking.com"])
    # Options: ["booking.com"], ["airbnb"], ["booking.com", "airbnb"]

     # ── Wizard signals ────────────────────────────────────────────────────────
    # These three are what the suggestion agents actually reason over, alongside
    # dates and budget. They have defaults so the Phase A CLI can ignore them.
    #
    # They exist as fields because the alternative was worse: the adapter used
    # to fold travel_type and preferences_text into `interests` by splitting the
    # free text on whitespace, which produced interest lists like
    # "adventure, Visit, all, popular, places, and, restaurants". Articles and
    # conjunctions were being sent to Claude as travel interests, and with_kids
    # was not being sent at all.
    with_kids: bool = False
    travel_style: str = "hybrid"          # "relax" | "active" | "hybrid"
    preferences_text: Optional[str] = None  # verbatim, never tokenised


# ── Per-agent result models ──────────────────────────────────────────────────

class FlightLeg(BaseModel):
    airline: str
    origin: str
    destination: str
    departure_time: str
    arrival_time: str
    duration_hours: float

class FlightOption(BaseModel):
    trip_type: str = "roundtrip"
    legs: list[FlightLeg] = Field(default_factory=list)
    price_usd: float
    booking_url: Optional[str] = None


class HotelOption(BaseModel):
    name: str
    location: str
    stars: Optional[float] = None
    price_per_night_usd: float
    total_price_usd: float
    booking_url: Optional[str] = None
    property_type: str = "hotel"
    provider: str = "booking.com"


class Activity(BaseModel):
    name: str
    description: str
    estimated_cost_usd: float
    duration_hours: float
    category: str                  # e.g. "food", "culture", "outdoor"
    booking_url: Optional[str] = None


class Country(BaseModel):
    """
    One candidate country proposed by the CountryAgent.

    Two notes, two different sources, deliberately:

      climate_note  comes from the model. What October is like in Japan does not
                    change year to year, so this is stable knowledge, not a
                    forecast. There is also no forecast to be had — Open-Meteo
                    needs coordinates, and at country-selection time there is no
                    city yet.

      safety_note   comes from the live State Department advisory feed, never
                    from the model. Advisories change, and stale or invented
                    safety guidance is worse than none. If the lookup fails the
                    claim is dropped rather than guessed.
    """
    name: str
    why_chosen_summary: str
    climate_note: str
    safety_note: str


class City(BaseModel):
    """
    One candidate city proposed by the CityAgent, within the committed country.

    No country field: there is exactly one country per trip, held by the country
    commit. A copy on every city could disagree with it.

    No safety_note either — advisories are published per country, so the note on
    Country covers every city in it. Duplicating it here would imply a
    city-level signal that does not exist.
    """
    city: str
    why_chosen_summary: str
    climate_note: str


class Citation(BaseModel):
    """
    A source behind an agent's claim, from Claude's web search tool.

    The tool returns url / title / cited_text on every web_search_result_location
    and citations are always enabled. Anthropic's terms require citations to be
    shown when API output is displayed to end users, so these are not optional
    decoration — the UI must render them.
    """
    url: str
    title: str
    cited_text: Optional[str] = None


class IntercityOption(BaseModel):
    """
    One way to get from the hub city to a spoke city and back.

    There is no API for "trains from Tokyo to Kyoto and what they cost", so this
    comes from Claude with web search rather than a booking provider. That makes
    the numbers indicative, not quotes: cost_usd is an estimate and sources is
    what it was estimated from. Both must reach the user.
    """
    mode: str                      # "train" | "bus" | "flight" | "ferry" | "car"
    description: str
    duration_hours: float
    cost_usd: float                # per person, round trip, estimated
    booking_note: Optional[str] = None
    sources: list[Citation] = Field(default_factory=list)


class WeatherSummary(BaseModel):
    location: str
    forecast_by_day: dict[str, str]   # "2025-08-01": "Sunny, 28°C"
    packing_tips: list[str]


class BudgetBreakdown(BaseModel):
    flights_usd: float = 0.0
    intercity_usd: float = 0.0     # hub-to-spoke day trips
    hotel_usd: float = 0.0
    activities_usd: float = 0.0
    miscellaneous_usd: float = 0.0
    total_usd: float = 0.0
    within_budget: bool = True
    notes: list[str] = Field(default_factory=list)


# ── The central object every agent reads and writes ──────────────────────────

class DayPlan(BaseModel):
    """
    One day in the trip's daily plan.

    Lives here (not schemas.py) so TravelPlan.day_by_day can reference it
    without a circular import — schemas.py imports FROM this module, so the
    dependency only runs one way. Re-exported from schemas.py, the same pattern
    as Country / City / Activity.

    city names where you are that day: under hub-and-spoke one plan spans the
    trip and moves between hub and spokes, so a day that doesn't name its city
    is ambiguous. activity_names is an ordered list of Activity.name values —
    a loose string reference, since all data lives in JSONB. This is the
    mutated form; free-text chat edits are applied here.
    """
    date: date
    city: str
    weather_line: str
    activity_names: list[str]


class TravelPlan(BaseModel):
    """
    The single source of truth passed between all agents.
    Orchestrator creates it. Each agent fills in its section.
    """
    request: TravelRequest

    # Agent results — all Optional because they start empty
    flight_options: Optional[list[FlightOption]] = None
    selected_flight: Optional[FlightOption] = None

    hotel_options: Optional[list[HotelOption]] = None
    selected_hotel: Optional[HotelOption] = None

    activities: Optional[list[Activity]] = None
    weather: Optional[WeatherSummary] = None
    budget: Optional[BudgetBreakdown] = None

    # Discovery agents write here. Declared, not set dynamically: TravelPlan is
    # a Pydantic model, so assigning an undeclared attribute raises — safe_run
    # then swallows it and the route returns 200 with an empty options list,
    # which reads as "no results found" rather than a crash. That exact bug cost
    # an evening.
    proposed_countries: Optional[list[Country]] = None
    proposed_cities: Optional[list[City]] = None
    intercity_options: Optional[list[IntercityOption]] = None
    
    # The CHOSEN day-trip segments (mode + dates per spoke), set by assembly from
    # the intercity commit. Distinct from intercity_options (the candidates the
    # agent proposed). Typed loosely: the concrete IntercitySegment lives in
    # schemas.py, which imports FROM this module, so annotating with it would be
    # circular. The orchestrator reads attributes off each item, not the type.
    selected_intercity: Optional[list] = None

    # The arranged day-by-day plan. The CLI pipeline leaves this None and lets
    # assemble_itinerary distribute activities; the wizard fills it from the
    # committed daily_plan, which is authoritative (the user may have reordered
    # it), so assembly renders these days rather than re-distributing. Declared,
    # not set dynamically — see proposed_countries above for why.
    day_by_day: Optional[list[DayPlan]] = None

    # Orchestrator writes here to explain its decisions
    itinerary_markdown: Optional[str] = None
    errors: list[str] = Field(default_factory=list)

    # Tracks which agents have completed
    completed_agents: list[str] = Field(default_factory=list)

    def mark_complete(self, agent_name: str) -> None:
        if agent_name not in self.completed_agents:
            self.completed_agents.append(agent_name)

    def add_error(self, agent_name: str, message: str) -> None:
        self.errors.append(f"[{agent_name}] {message}")

    def is_ready_for_output(self) -> bool:
        required = {"weather", "flights", "hotels", "activities", "budget"}
        return required.issubset(set(self.completed_agents))