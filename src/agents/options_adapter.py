from __future__ import annotations
from datetime import date
from typing import Any

from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.flight_agent import FlightAgent
from src.agents.hotel_agent import HotelAgent
from src.agents.activities_agent import ActivitiesAgent
from src.agents.destination_agent import DestinationAgent


# ─────────────────────────────────────────────────────────────────────────────
# Options adapter
# ─────────────────────────────────────────────────────────────────────────────
# The wizard's state is spread across commit rows: the setup commit holds the
# dates / budget / origin, and each stop holds its own city. The Phase A agents,
# however, are built around a single-shot TravelPlan whose `request` is a
# TravelRequest. This adapter constructs a synthetic TravelPlan from the
# wizard's committed state, runs the appropriate agent via safe_run (so a
# failure degrades to mock rather than raising), and reads the options back off
# the plan as plain dicts matching the frontend schemas.
#
# One agent instance per call is fine — they're cheap to construct and hold no
# state between runs.
#
# Feature flags are respected implicitly: the flight and hotel agents check
# SKYSCANNER_ENABLED / AIRBNB_ENABLED internally and fall back to mock when the
# flags are False, so the adapter simply gets whatever the agent decided.


def _synthetic_request(setup: dict[str, Any], city: str) -> TravelRequest:
    """
    Build a TravelRequest from the committed setup payload plus a target city.

    setup is the SetupCommitData dict:
      origin, departure_date, return_date, num_travelers, travel_type,
      budget_amount, budget_currency, with_kids, preferences_text, multi_city
    """
    return TravelRequest(
        origin=setup.get("origin", ""),
        destination=city,
        departure_date=date.fromisoformat(setup["departure_date"]),
        return_date=date.fromisoformat(setup["return_date"]),
        budget_usd=float(setup.get("budget_amount") or 0) or 3000.0,
        travelers=int(setup.get("num_travelers", 1)),
        interests=_interests_from_setup(setup),
        trip_type="roundtrip",
    )


def _interests_from_setup(setup: dict[str, Any]) -> list[str]:
    """Derive interest tags from travel_type + free-text preferences."""
    interests: list[str] = []
    tt = setup.get("travel_type")
    if tt == "relax":
        interests.append("relaxation")
    elif tt == "active":
        interests.append("adventure")
    prefs = (setup.get("preferences_text") or "").strip()
    if prefs:
        # Split loose comma/space-separated interests
        interests.extend(
            p.strip() for p in prefs.replace(",", " ").split() if p.strip()
        )
    return interests


# ─────────────────────────────────────────────────────────────────────────────
# Per-stage option fetchers
# ─────────────────────────────────────────────────────────────────────────────
# Each returns a list of plain dicts already shaped for the matching frontend
# *CommitData payload. The route serialises these straight to JSON.


def destination_options(setup: dict[str, Any]) -> list[dict]:
    """Run the destination-discovery agent. City is not yet known here."""
    # A placeholder destination keeps TravelRequest valid; the agent ignores it.
    req = _synthetic_request(setup, city="")
    plan = TravelPlan(request=req)
    plan = DestinationAgent().safe_run(plan)
    return [d.model_dump() for d in (plan.proposed_destinations or [])]


def flight_options(setup: dict[str, Any], city: str) -> list[dict]:
    req = _synthetic_request(setup, city)
    plan = TravelPlan(request=req)
    plan = FlightAgent().safe_run(plan)
    return [f.model_dump() for f in (plan.flight_options or [])]


def accommodation_options(setup: dict[str, Any], city: str) -> list[dict]:
    req = _synthetic_request(setup, city)
    plan = TravelPlan(request=req)
    plan = HotelAgent().safe_run(plan)
    return [h.model_dump() for h in (plan.hotel_options or [])]


def activities_options(setup: dict[str, Any], city: str) -> list[dict]:
    req = _synthetic_request(setup, city)
    plan = TravelPlan(request=req)
    plan = ActivitiesAgent().safe_run(plan)
    return [a.model_dump() for a in (plan.activities or [])]


# ── Dispatch table ────────────────────────────────────────────────────────────
# Maps a stage name to its fetcher. destination takes no city; the others do.

STAGE_FETCHERS = {
    "destination": destination_options,
    "flights": flight_options,
    "accommodation": accommodation_options,
    "activities": activities_options,
}