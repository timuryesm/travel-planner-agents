"""
Assembly — turn a wizard trip's committed choices into a final itinerary.

The orchestrator's assemble_itinerary(plan) and BudgetAgent both speak
TravelPlan / plain numbers, not SQLAlchemy. The wizard's choices live in commit
rows. This module is the one place that reads those rows, so the ORM never
leaks into an agent — the same boundary options_adapter holds for the options
side. Everything here is "commits in, TravelPlan out"; the agents are unchanged.

Two functions the route composes:

  build_plan_from_commits(trip)   commit rows → a populated TravelPlan, exactly
                                  the shape the CLI pipeline would have produced.
  wizard_costs_from_commits(trip) the same rows → the numbers BudgetAgent.
                                  aggregate() wants. Shares the extraction with
                                  build_plan_from_commits so the itinerary and
                                  the budget can never disagree about what was
                                  chosen.

Single-city only for now. Multi-city assembly — days that move between hub and
spokes, per-stop activities, intercity legs — is Track 2 (step 19). Where that
boundary bites is marked inline.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from src.db.models import Trip
from src.state.enums import StopLevelStage, TripLevelStage
from src.state.schemas import (
    AccommodationCommitData,
    ActivitiesCommitData,
    DailyPlanCommitData,
    FlightsCommitData,
    SetupCommitData,
)
from src.state.travel_plan import TravelPlan, TravelRequest


# ── Commit access ─────────────────────────────────────────────────────────────

def _trip_commit(trip: Trip, stage: str) -> Optional[dict[str, Any]]:
    """The commit_data for a trip-level stage, or None if not completed."""
    c = next((c for c in trip.trip_stage_commits if c.stage == stage), None)
    if c is None or not c.completed or not c.commit_data:
        return None
    return c.commit_data


def _stop_commit(trip: Trip, stop_index: int, stage: str) -> Optional[dict[str, Any]]:
    """The commit_data for a stop-level stage, or None if not completed."""
    stop = next((s for s in trip.stops if s.stop_index == stop_index), None)
    if stop is None:
        return None
    c = next((c for c in stop.stop_stage_commits if c.stage == stage), None)
    if c is None or not c.completed or not c.commit_data:
        return None
    return c.commit_data


# ── Extraction ────────────────────────────────────────────────────────────────

class AssemblyNotReady(ValueError):
    """
    Assembly was requested before the trip has what it needs.

    Setup and city are non-negotiable — without them there's no request and no
    hub, so there's nothing to assemble. Flights, accommodation and activities
    can each be legitimately absent (skipped, or self-provided), and assembly
    proceeds with what's there; the budget notes say what was left out. The
    route turns this into a 409.
    """


def _require_setup(trip: Trip) -> SetupCommitData:
    data = _trip_commit(trip, TripLevelStage.setup.value)
    if data is None:
        raise AssemblyNotReady("Setup must be completed before assembling a plan.")
    return SetupCommitData.model_validate(data)


def _hub(trip: Trip):
    hub = next((s for s in trip.stops if s.stop_index == 0), None)
    if hub is None:
        raise AssemblyNotReady("A city must be chosen before assembling a plan.")
    return hub


def build_plan_from_commits(trip: Trip) -> TravelPlan:
    """
    Rebuild the TravelPlan the CLI pipeline would have produced, from commits.

    Populates request, selected_flight, selected_hotel, activities, weather, and
    the committed day_by_day. The orchestrator's assemble_itinerary reads these
    fields and doesn't care that a wizard, not a pipeline, filled them.
    """
    setup = _require_setup(trip)
    hub = _hub(trip)

    req = TravelRequest(
        origin=setup.origin,
        destination=hub.city,               # the hub is the trip's "where"
        departure_date=setup.departure_date,
        return_date=setup.return_date,
        budget_usd=float(setup.budget_amount or 0) or 3000.0,
        travelers=setup.num_travelers,
        trip_type="roundtrip",
        with_kids=setup.with_kids,
        travel_style=setup.travel_type,
        preferences_text=setup.preferences_text,
        # getattr guard: a trip whose setup commit predates the language
        # field (added step 12) validates with the default, but belt-and-braces
        # against an old row missing it entirely.
        language=getattr(setup, "language", "en"),
    )
    plan = TravelPlan(request=req)

    # Flight — optional (may be skipped or self-provided with an empty legs list)
    flights = _trip_commit(trip, TripLevelStage.flights.value)
    if flights and flights.get("selected"):
        plan.selected_flight = FlightsCommitData.model_validate(flights).selected

    # Hotel — optional
    hotel = _trip_commit(trip, TripLevelStage.accommodation.value)
    if hotel and hotel.get("selected"):
        plan.selected_hotel = AccommodationCommitData.model_validate(hotel).selected

    # Activities — stop-level. SINGLE-CITY: only the hub (index 0). Multi-city
    # concatenates every stop's chosen list in stop order; that's step 19.
    acts = _stop_commit(trip, 0, StopLevelStage.activities.value)
    if acts:
        plan.activities = ActivitiesCommitData.model_validate(acts).chosen or []

    # Daily plan — the authoritative day-by-day the user may have arranged.
    # Assembly renders THIS rather than re-distributing activities, so the order
    # the user chose survives into the final document.
    daily = _trip_commit(trip, TripLevelStage.daily_plan.value)
    if daily:
        plan.day_by_day = DailyPlanCommitData.model_validate(daily).day_by_day

    return plan


def wizard_costs_from_commits(trip: Trip) -> dict[str, Any]:
    """
    The numbers BudgetAgent.aggregate() needs, read from the same commits.

    nights is the HOTEL stay (check_out - check_in), not the trip window: a
    multi-city trip may check out early for nights spent in spokes, and misc is
    per-night, so the stay is the honest basis. Single-city they're equal.
    """
    setup = _require_setup(trip)
    _hub(trip)  # assert a hub exists; cost extraction below tolerates absent parts

    flights_usd = 0.0
    flights = _trip_commit(trip, TripLevelStage.flights.value)
    if flights and flights.get("selected"):
        flights_usd = FlightsCommitData.model_validate(flights).selected.price_usd

    hotel_usd = 0.0
    nights = (setup.return_date - setup.departure_date).days
    hotel = _trip_commit(trip, TripLevelStage.accommodation.value)
    if hotel and hotel.get("selected"):
        acc = AccommodationCommitData.model_validate(hotel)
        hotel_usd = acc.selected.total_price_usd
        # Prefer the committed stay length over the trip window.
        nights = (acc.check_out - acc.check_in).days

    activities_usd = 0.0
    acts = _stop_commit(trip, 0, StopLevelStage.activities.value)
    if acts:
        chosen = ActivitiesCommitData.model_validate(acts).chosen or []
        activities_usd = sum(a.estimated_cost_usd for a in chosen)

    missing: list[str] = []
    if flights_usd == 0.0 and not (flights and flights.get("selected")):
        missing.append("flights")
    if not (hotel and hotel.get("selected")):
        missing.append("accommodation")
    if not acts or not ActivitiesCommitData.model_validate(acts).chosen:
        missing.append("activities")

    return {
        "flights_usd": flights_usd,
        "hotel_usd": hotel_usd,
        "activities_usd": activities_usd,
        "intercity_usd": 0.0,          # single-city; Track 2 fills this
        "budget_usd": req_budget(setup),
        "nights": nights,
        "travelers": setup.num_travelers,
        "missing": missing,
    }


def req_budget(setup: SetupCommitData) -> float:
    return float(setup.budget_amount or 0) or 3000.0


def generated_at() -> datetime:
    return datetime.now(timezone.utc)