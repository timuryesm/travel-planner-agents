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


# ── Per-agent result models ──────────────────────────────────────────────────

class FlightOption(BaseModel):
    airline: str
    departure_time: str
    arrival_time: str
    duration_hours: float
    price_usd: float
    booking_url: Optional[str] = None


class HotelOption(BaseModel):
    name: str
    location: str
    stars: Optional[float] = None
    price_per_night_usd: float
    total_price_usd: float
    booking_url: Optional[str] = None


class Activity(BaseModel):
    name: str
    description: str
    estimated_cost_usd: float
    duration_hours: float
    category: str                  # e.g. "food", "culture", "outdoor"
    booking_url: Optional[str] = None


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