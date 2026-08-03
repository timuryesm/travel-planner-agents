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
    IntercityCommitData,
    AccommodationCommitData,
    ActivitiesCommitData,
    CityCommitData,
    CountryCommitData,
    DailyPlanCommitData,
    FinalCommitData,
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

    # Activities — stop-level, gathered across EVERY stop in stop order: the hub
    # first, then each spoke. Multi-city (step 19): a spoke's activities are the
    # ones you do on its day trip, and they belong in the plan and the budget
    # just like the hub's. Single-city: this is just the hub, unchanged.
    all_activities = []
    for stop in sorted(trip.stops, key=lambda s: s.stop_index):
        sc = _stop_commit(trip, stop.stop_index, StopLevelStage.activities.value)
        if sc:
            all_activities.extend(ActivitiesCommitData.model_validate(sc).chosen or [])
    plan.activities = all_activities

    # Intercity — the chosen day-trip segments (mode + dates per spoke). Set so
    # the orchestrator can render a day-trips section. None on single-city.
    inter = _trip_commit(trip, TripLevelStage.intercity.value)
    if inter:
        plan.selected_intercity = IntercityCommitData.model_validate(inter).segments

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

    # Activities across every stop (hub + spokes), same as build_plan_from_commits.
    activities_usd = 0.0
    any_activities = False
    for stop in trip.stops:
        sc = _stop_commit(trip, stop.stop_index, StopLevelStage.activities.value)
        if sc:
            chosen = ActivitiesCommitData.model_validate(sc).chosen or []
            if chosen:
                any_activities = True
            activities_usd += sum(a.estimated_cost_usd for a in chosen)

    # Intercity — the day trips. cost_usd is per person, round trip, so it scales
    # with travelers, same as flights. Absent (0) on single-city trips, where
    # there is no intercity commit.
    intercity_usd = 0.0
    inter = _trip_commit(trip, TripLevelStage.intercity.value)
    if inter:
        segments = IntercityCommitData.model_validate(inter).segments
        intercity_usd = sum(seg.selected.cost_usd for seg in segments) * setup.num_travelers

    missing: list[str] = []
    if flights_usd == 0.0 and not (flights and flights.get("selected")):
        missing.append("flights")
    if not (hotel and hotel.get("selected")):
        missing.append("accommodation")
    if not any_activities:
        missing.append("activities")

    return {
        "flights_usd": flights_usd,
        "hotel_usd": hotel_usd,
        "activities_usd": activities_usd,
        "intercity_usd": intercity_usd,   # real day-trip cost; 0 on single-city
        "budget_usd": req_budget(setup),
        "nights": nights,
        "travelers": setup.num_travelers,
        "missing": missing,
    }


def req_budget(setup: SetupCommitData) -> float:
    return float(setup.budget_amount or 0) or 3000.0


def generated_at() -> datetime:
    return datetime.now(timezone.utc)


# ── Export ────────────────────────────────────────────────────────────────────

def export_inputs_from_commits(trip: Trip) -> dict[str, Any]:
    """
    The validated payloads render_export_markdown needs, from commit rows.

    Lives here, not in the export route: this module is the one place that
    reads commit rows (see module docstring), and export is another consumer
    of them, not a new boundary.

    The final commit is the gate. Country and city missing UNDER a completed
    final commit should be impossible — cascade-invalidate would have taken
    final down with them — so that case raises AssemblyNotReady too (a 409
    the user can act on) rather than crashing into a 500.
    """
    final = _trip_commit(trip, TripLevelStage.final.value)
    if final is None:
        raise AssemblyNotReady("The plan has not been confirmed yet.")

    setup = _require_setup(trip)
    country = _trip_commit(trip, TripLevelStage.country.value)
    cities = _trip_commit(trip, TripLevelStage.city.value)
    if country is None or cities is None:
        raise AssemblyNotReady("The plan is missing its destination commits.")

    country_row = next(
        (c for c in trip.trip_stage_commits
         if c.stage == TripLevelStage.country.value and c.completed),
        None,
    )

    return {
        "final": FinalCommitData.model_validate(final),
        "setup": setup,
        "country": CountryCommitData.model_validate(country),
        "cities": CityCommitData.model_validate(cities),
        # updated_at, not created_at: commit rows are pre-created as
        # 'unvisited' when the trip is created, so created_at is the trip's
        # birth date. updated_at is when this commit actually landed — i.e.
        # when the State Dept advisory in it was fetched.
        "advisory_as_of": country_row.updated_at.date() if country_row else None,
    }