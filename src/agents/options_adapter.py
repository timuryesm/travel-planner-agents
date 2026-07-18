from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

from src.state.schemas import SetupCommitData
from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.flight_agent import FlightAgent
from src.agents.hotel_agent import HotelAgent
from src.agents.activities_agent import ActivitiesAgent
from src.agents.country_agent import CountryAgent
from src.agents.city_agent import CityAgent


# ─────────────────────────────────────────────────────────────────────────────
# Options adapter
# ─────────────────────────────────────────────────────────────────────────────
# The wizard's state is spread across commit rows: setup holds the dates,
# budget and origin; country holds the country; city holds the ordered city
# list; each stop holds its own city and dates. The Phase A agents, however,
# are built around a single-shot TravelPlan whose `request` is a TravelRequest.
#
# This adapter constructs a synthetic TravelPlan from the wizard's committed
# state, runs the appropriate agent via safe_run, and reads the options back
# off the plan as plain dicts matching the frontend schemas.
#
# One agent instance per call is fine — they're cheap to construct and hold no
# state between runs. Hints like `exclude` are passed to the constructor for
# that reason.
#
# Feature flags are respected implicitly: the flight and hotel agents check
# SKYSCANNER_ENABLED / AIRBNB_ENABLED internally and fall back to mock when the
# flags are False, so the adapter simply gets whatever the agent decided.


class AgentFailed(RuntimeError):
    """
    A discovery agent failed and there is no honest answer to serve.

    The route turns this into a 502. See _discovery_result for why only the
    discovery stages raise it.
    """


@dataclass
class OptionsContext:
    """
    Everything a fetcher might need, assembled once by the route.

    Every fetcher takes this and returns a list of dicts. A uniform signature
    is what lets the route dispatch through a plain dict lookup instead of a
    branch per stage — which matters now that the stages need different subsets
    of the trip's state. Under the old design there were two shapes ("needs a
    city" / "doesn't"), and the route could get away with an if.

    Deliberately ORM-free: the route reads the Trip and passes plain values, so
    the adapter and the agents never see a SQLAlchemy object and stay testable
    without a database.

    hub_city is stops[0].city — the city flown into, where the hotel is, and
    where every day-trip starts and ends. Both flights and accommodation are
    about the hub and nothing else.
    """
    setup: SetupCommitData
    country: Optional[str] = None
    hub_city: Optional[str] = None

    # Stop-level stages (activities) target one city and its dates.
    target_city: Optional[str] = None
    target_start_date: Optional[date] = None
    target_end_date: Optional[date] = None

    # Hints from the request body.
    exclude: list[str] = field(default_factory=list)
    preference_text: Optional[str] = None
    limit: Optional[int] = None


def _synthetic_request(ctx: OptionsContext, destination: str) -> TravelRequest:
    """
    Build a TravelRequest from the committed setup payload plus a destination.

    `destination` is whatever "where" means at the calling stage: the hub city
    for flights and accommodation, the country for city discovery, the target
    city for activities, and "" for country discovery, where no destination
    exists yet. TravelRequest has exactly one such field and each fetcher fills
    it with the answer relevant to its own question.

    travel_style, with_kids and preferences_text are passed through as
    themselves. They used to be folded into `interests` — with_kids silently
    dropped and preferences_text split on whitespace, so a sentence like
    "Visit all popular places and restaurants" reached Claude as the interests
    ["Visit", "all", "popular", "places", "and", "restaurants"]. The signals the
    agent is supposed to reason over were being destroyed on the way in.

    Note this carries the SETUP preference text only. A stage-scoped hint from
    the request body travels separately, on the agent constructor, because it
    answers a different question — see CityAgent and ActivitiesAgent.
    """
    setup = ctx.setup
    return TravelRequest(
        origin=setup.origin,
        destination=destination,
        departure_date=setup.departure_date,
        return_date=setup.return_date,
        budget_usd=float(setup.budget_amount or 0) or 3000.0,
        travelers=setup.num_travelers,
        trip_type="roundtrip",
        with_kids=setup.with_kids,
        travel_style=setup.travel_type,
        preferences_text=setup.preferences_text,
    )


def _discovery_result(plan: TravelPlan, options: list | None, stage: str) -> list[dict]:
    """
    Read a discovery agent's results, or raise if it failed.

    safe_run catches everything, so a crashed agent hands back a plan with its
    result field still None and the fetcher would answer []. The route then
    serves 200 with no options, and the browser cannot tell "the agent died"
    from "there is nothing to suggest". That happened three times in one
    afternoon: an undeclared Pydantic field, a markdown fence, and a missing
    country — all reported to the user as a cheerful empty list.

    Degrading to [] is right for FLIGHTS, ACCOMMODATION and ACTIVITIES, where a
    fallback (mock providers, or the generic activity pool) is a real answer and
    losing the tailored version shouldn't cost the user their progress. It is
    wrong for COUNTRY and CITY: there is nothing to degrade to, an empty list is
    a dead wizard, and the user's only move is a refresh they have no reason to
    attempt. So only those two go through this function and raise; the rest read
    their results directly and tolerate an empty list.

    plan.errors is populated by safe_run's except branch, which is what makes
    the distinction readable here without changing safe_run's contract.
    """
    if plan.errors:
        raise AgentFailed(f"{stage}: {plan.errors[-1]}")
    if options is None:
        # No exception, no results. Shouldn't happen — but returning [] here
        # would recreate exactly the silence this function exists to remove.
        raise AgentFailed(f"{stage}: agent completed without producing results")
    return [o.model_dump() for o in options]


# ─────────────────────────────────────────────────────────────────────────────
# Per-stage option fetchers
# ─────────────────────────────────────────────────────────────────────────────
# Each takes an OptionsContext and returns a list of plain dicts already shaped
# for the matching frontend *CommitData payload. The route serialises these
# straight to JSON.


def country_options(ctx: OptionsContext) -> list[dict]:
    """Run the country-discovery agent. No city is known at this point."""
    # A placeholder destination keeps TravelRequest valid; the agent ignores it.
    req = _synthetic_request(ctx, destination="")
    plan = TravelPlan(request=req)
    plan = CountryAgent(exclude=ctx.exclude, limit=ctx.limit).safe_run(plan)
    return _discovery_result(plan, plan.proposed_countries, "country")


def city_options(ctx: OptionsContext) -> list[dict]:
    """
    Cities within the committed country.

    The country goes in as the destination — it is the "where" this stage
    reasons about. preference_text is the hint the user typed on THIS stage and
    goes to the constructor, not into the request: the request already carries
    the setup preferences, and the two are different questions.
    """
    req = _synthetic_request(ctx, destination=ctx.country or "")
    plan = TravelPlan(request=req)
    plan = CityAgent(
        exclude=ctx.exclude,
        limit=ctx.limit,
        preference_text=ctx.preference_text,
    ).safe_run(plan)
    return _discovery_result(plan, plan.proposed_cities, "city")


def flight_options(ctx: OptionsContext) -> list[dict]:
    """
    One roundtrip, origin to hub and back.

    Not per-city: spoke cities are reached from the hub, which is the intercity
    stage's business.

    Degrades to [] on failure rather than raising — see _discovery_result.
    """
    req = _synthetic_request(ctx, destination=ctx.hub_city or "")
    plan = TravelPlan(request=req)
    plan = FlightAgent().safe_run(plan)
    return [f.model_dump() for f in (plan.flight_options or [])]


def accommodation_options(ctx: OptionsContext) -> list[dict]:
    """One stay, in the hub city, for the whole period."""
    req = _synthetic_request(ctx, destination=ctx.hub_city or "")
    plan = TravelPlan(request=req)
    plan = HotelAgent().safe_run(plan)
    return [h.model_dump() for h in (plan.hotel_options or [])]


def activities_options(ctx: OptionsContext) -> list[dict]:
    """
    Things to do in one city — the only stage that repeats per stop.

    Carries all three hints: preference_text (what they want from activities),
    exclude (names already shown, for regenerate/expand), and limit (how many).
    Like flights and accommodation it degrades to [] on failure — the agent's
    own generic pool is the fallback, so a crash there is a quieter list, not a
    dead end.
    """
    req = _synthetic_request(ctx, destination=ctx.target_city or "")
    plan = TravelPlan(request=req)
    plan = ActivitiesAgent(
        exclude=ctx.exclude,
        limit=ctx.limit,
        preference_text=ctx.preference_text,
    ).safe_run(plan)
    return [a.model_dump() for a in (plan.activities or [])]


# ── Dispatch table ────────────────────────────────────────────────────────────
# Maps a stage name to its fetcher. Uniform signature: (OptionsContext) -> list.
#
# Not every wizard stage is here. setup and daily_plan propose nothing; final
# has its own endpoint because it returns one assembled object rather than a
# list of options. intercity lands in Track 2.

STAGE_FETCHERS: dict[str, Callable[[OptionsContext], list[dict]]] = {
    "country": country_options,
    "city": city_options,
    "flights": flight_options,
    "accommodation": accommodation_options,
    "activities": activities_options,
}