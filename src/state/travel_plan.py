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


class Destination(BaseModel):
    """
    One candidate city proposed by the DestinationAgent.

    Defined here rather than in schemas.py because TravelPlan needs it and
    schemas.py already imports FROM this module — declaring it there and
    importing it back would be a circular import. schemas.py re-exports it,
    so `from src.state.schemas import Destination` keeps working everywhere.

    Same shape as DestinationCommitData's list element by design: the agent's
    output IS the wizard's commit payload, and one definition means the two
    can't drift apart.
    """
    city: str
    country: str
    why_chosen_summary: str
    season_note: str
    safety_note: str   # sourced from a live travel-advisory signal, not model memory


class WeatherSummary(BaseModel):
    location: str
    forecast_by_day: dict[str, str]   # "2025-08-01": "Sunny, 28°C"
    packing_tips: list[str]


class BudgetBreakdown(BaseModel):
    flights_usd: float = 0.0
    hotel_usd: float = 0.0
    activities_usd: float = 0.0
    miscellaneous_usd: float = 0.0
    total_usd: float = 0.0
    within_budget: bool = True
    notes: list[str] = Field(default_factory=list)


# ── The central object every agent reads and writes ──────────────────────────

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

    # DestinationAgent writes here. Declared rather than set dynamically:
    # TravelPlan is a Pydantic model, so assigning an undeclared attribute
    # raises ValueError — safe_run then swallows it and the route returns
    # 200 with an empty options list, which reads as "no results found"
    # rather than a crash.
    proposed_destinations: Optional[list[Destination]] = None

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