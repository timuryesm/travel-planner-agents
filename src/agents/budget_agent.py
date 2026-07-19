from __future__ import annotations
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, BudgetBreakdown


class BudgetAgent(BaseAgent):
    """
    Totals the trip's costs and checks them against the budget.

    Two entry points share ONE calculation:

      run(plan)     the CLI / Phase-A path. Reads the chosen flight, hotel and
                    activities off the TravelPlan fields the pipeline populated,
                    then calls aggregate().

      aggregate(…)  a pure function of numbers — no TravelPlan, no ORM, no
                    commit rows. This is what the wizard's assembly step calls
                    too, after it has read the same figures out of the commit
                    rows itself.

    Why aggregate() takes numbers rather than a plan or the trip:

    The two callers hold their data in completely different shapes. The CLI has
    a populated TravelPlan; the wizard has SQLAlchemy commit rows
    (FlightsCommitData.selected, AccommodationCommitData.selected, each stop's
    ActivitiesCommitData.chosen, plus intercity segments). If aggregate() knew
    about either shape it would be coupled to that caller — and if it reached
    into commit rows it would drag the ORM into a Phase-A agent, which is the
    boundary options_adapter exists to hold. Reducing both callers to a handful
    of floats is what makes the total genuinely one implementation instead of
    two that are supposed to match.

    The extraction that differs per caller lives WITH that caller: run() below
    for the plan, and the assembly layer (step 14) for the commits. Each is
    small and about its own data source; neither belongs in the other.
    """

    name = "budget"

    # Estimated daily miscellaneous spend (local transit, snacks, tips) per person.
    MISC_PER_DAY_USD = 40.0

    # ── Shared calculation ───────────────────────────────────────────────

    @staticmethod
    def aggregate(
        *,
        flights_usd: float,
        hotel_usd: float,
        activities_usd: float,
        budget_usd: float,
        nights: int,
        travelers: int,
        intercity_usd: float = 0.0,
        missing: list[str] | None = None,
    ) -> BudgetBreakdown:
        """
        Total the parts, add estimated misc, and compare to the budget.

        Keyword-only on purpose: eight numeric-ish arguments in a row is exactly
        where a positional call silently transposes hotel and flights and every
        total is quietly wrong. Naming them makes both call sites readable and
        transpositions impossible.

        `nights` is passed in, NOT re-derived from trip dates. Under hub-and-
        spoke the hotel stay is check-out − check-in, which can be shorter than
        the trip when nights are spent in spokes — deriving misc from the trip
        window would overcount. Single-city they're equal; the caller decides.
        misc is per-person-per-night, so it scales with both.

        `intercity_usd` defaults to 0 — the CLI has no day-trips, and single-
        city wizard trips have none either. Track 2 fills it.

        `missing` names cost components that were skipped or never chosen
        (e.g. "flights"), so a partial plan's total is honest about what it
        omits rather than looking complete at a suspiciously low number.
        """
        misc_usd = round(BudgetAgent.MISC_PER_DAY_USD * max(nights, 0) * travelers, 2)

        total = round(
            flights_usd + intercity_usd + hotel_usd + activities_usd + misc_usd, 2
        )

        return BudgetBreakdown(
            flights_usd=round(flights_usd, 2),
            intercity_usd=round(intercity_usd, 2),
            hotel_usd=round(hotel_usd, 2),
            activities_usd=round(activities_usd, 2),
            miscellaneous_usd=misc_usd,
            total_usd=total,
            within_budget=total <= budget_usd,
            notes=BudgetAgent._build_notes(total, budget_usd, missing or []),
        )

    # ── CLI / Phase-A entry point ────────────────────────────────────────

    def run(self, plan: TravelPlan) -> TravelPlan:
        req = plan.request
        nights = (req.return_date - req.departure_date).days

        self.logger.info("Aggregating costs from all agents")

        flights_usd = plan.selected_flight.price_usd if plan.selected_flight else 0.0
        hotel_usd = plan.selected_hotel.total_price_usd if plan.selected_hotel else 0.0
        activities_usd = (
            sum(a.estimated_cost_usd for a in plan.activities) if plan.activities else 0.0
        )

        # Which components are absent, so the notes can say so. The CLI pipeline
        # has no intercity leg, so it's never listed here.
        missing: list[str] = []
        if not plan.selected_flight:
            missing.append("flights")
        if not plan.selected_hotel:
            missing.append("accommodation")
        if not plan.activities:
            missing.append("activities")

        breakdown = self.aggregate(
            flights_usd=flights_usd,
            hotel_usd=hotel_usd,
            activities_usd=activities_usd,
            budget_usd=req.budget_usd,
            nights=nights,
            travelers=req.travelers,
            intercity_usd=0.0,
            missing=missing,
        )

        plan.budget = breakdown
        plan.mark_complete(self.name)

        status = "within budget" if breakdown.within_budget else "OVER budget"
        self.logger.info(
            f"Total: ${breakdown.total_usd:,.2f} / ${req.budget_usd:,.2f} ({status})"
        )
        return plan

    # ── Notes ────────────────────────────────────────────────────────────

    @staticmethod
    def _build_notes(total: float, budget: float, missing: list[str]) -> list[str]:
        """
        Human-facing budget notes. Static and text-only so both entry points
        produce identical wording — the note is part of the shared result, not
        something each caller phrases its own way.
        """
        notes: list[str] = []

        remaining = budget - total
        if remaining >= 0:
            notes.append(
                f"${remaining:,.2f} under budget — room for upgrades or extra activities"
            )
        else:
            notes.append(
                f"${abs(remaining):,.2f} over budget — consider cheaper flights or accommodation"
            )

        # One line per omitted component. Phrased so the total's caveats are
        # explicit: a cheap-looking plan that's missing a flight isn't a bargain.
        label = {
            "flights": "No flight selected — flight cost not included",
            "accommodation": "No accommodation selected — lodging cost not included",
            "activities": "No activities planned — activity cost not included",
            "intercity": "Day-trip travel not yet costed — intercity total not included",
        }
        for component in missing:
            text = label.get(component)
            if text:
                notes.append(f"⚠️ {text}")

        return notes