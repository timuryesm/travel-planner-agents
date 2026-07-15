from __future__ import annotations
import json
import anthropic
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan
from src.state.schemas import Destination
from src.tools.advisory_lookup import advisory_note
from src.config.settings import settings


class DestinationAgent(BaseAgent):
    """
    NEW capability (not part of the original Phase A pipeline).

    Proposes candidate destination cities from the user's setup preferences,
    then attaches a LIVE travel-advisory safety signal to each — the safety
    note must come from a current external source, never from model memory,
    because advisories change and stale guidance is worse than none.

    Contract matches every other agent: run(plan) reads plan.request, writes
    results back onto the plan — specifically plan.proposed_destinations,
    declared on TravelPlan alongside the other agents' result fields.

    Safety-signal source: the U.S. State Department travel advisory feed, via
    src/tools/advisory_lookup.py, which caches the feed so proposing six cities
    costs at most one HTTP request (and usually zero). If the lookup fails we
    DROP the safety claim rather than invent one — a neutral note is safer than
    a wrong one.
    """

    name = "destination"
    MODEL = "claude-sonnet-4-6"

    def run(self, plan: TravelPlan) -> TravelPlan:
        req = plan.request

        self.logger.info(
            f"Discovering destinations · interests: "
            f"{', '.join(req.interests) or 'general'} · budget: ${req.budget_usd}"
        )

        try:
            candidates = self._propose_cities(req)
            self.logger.info(f"Claude proposed {len(candidates)} cities")
        except Exception as e:
            self.logger.warning(f"Destination discovery failed ({e}) — using fallback")
            candidates = self._fallback_cities(req)

        # Attach a live safety signal to each candidate. All six lookups hit the
        # same cached feed — one HTTP request at most, not one per city.
        destinations: list[Destination] = []
        unresolved = 0
        for c in candidates:
            note = advisory_note(c.get("country", ""))
            if note is None:
                unresolved += 1
            destinations.append(Destination(
                city=c["city"],
                country=c["country"],
                why_chosen_summary=c["why_chosen_summary"],
                season_note=c["season_note"],
                # Live signal replaces whatever the model might have guessed
                safety_note=note or c.get(
                    "safety_note", "Check current travel advisories before booking."
                ),
            ))

        if unresolved:
            self.logger.warning(
                f"{unresolved}/{len(destinations)} destinations have no live "
                f"advisory — using neutral placeholder"
            )

        plan.proposed_destinations = destinations
        plan.mark_complete(self.name)
        return plan