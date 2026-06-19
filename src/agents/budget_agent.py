from __future__ import annotations
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, BudgetBreakdown


class BudgetAgent(BaseAgent):

    name = "budget"

    # Estimated daily miscellaneous spend (local transit, snacks, tips) per person
    MISC_PER_DAY_USD = 40.0

    def run(self, plan: TravelPlan) -> TravelPlan:
        req    = plan.request
        nights = (req.return_date - req.departure_date).days

        self.logger.info("Aggregating costs from all agents")

        # ── Pull costs from each agent's results ─────────────────────────
        flights_usd = (
            plan.selected_flight.price_usd
            if plan.selected_flight else 0.0
        )

        hotel_usd = (
            plan.selected_hotel.total_price_usd
            if plan.selected_hotel else 0.0
        )

        activities_usd = (
            sum(a.estimated_cost_usd for a in plan.activities)
            if plan.activities else 0.0
        )

        misc_usd = round(self.MISC_PER_DAY_USD * nights * req.travelers, 2)

        total = round(flights_usd + hotel_usd + activities_usd + misc_usd, 2)

        # ── Build the breakdown ──────────────────────────────────────────
        breakdown = BudgetBreakdown(
            flights_usd=round(flights_usd, 2),
            hotel_usd=round(hotel_usd, 2),
            activities_usd=round(activities_usd, 2),
            miscellaneous_usd=misc_usd,
            total_usd=total,
            within_budget=total <= req.budget_usd,
            notes=self._build_notes(plan, total, req.budget_usd, nights),
        )

        plan.budget = breakdown
        plan.mark_complete(self.name)

        status = "within budget" if breakdown.within_budget else "OVER budget"
        self.logger.info(f"Total: ${total:,.2f} / ${req.budget_usd:,.2f} ({status})")
        return plan

    # ── Helpers ──────────────────────────────────────────────────────────

    def _build_notes(
        self,
        plan: TravelPlan,
        total: float,
        budget: float,
        nights: int,
    ) -> list[str]:
        notes: list[str] = []

        remaining = budget - total
        if remaining >= 0:
            notes.append(f"${remaining:,.2f} under budget — room for upgrades or extra activities")
        else:
            notes.append(f"${abs(remaining):,.2f} over budget — consider cheaper flights or accommodation")

        if not plan.selected_flight:
            notes.append("⚠️ No flight selected — flight cost not included")
        if not plan.selected_hotel:
            notes.append("⚠️ No accommodation selected — lodging cost not included")
        if not plan.activities:
            notes.append("⚠️ No activities planned — activity cost not included")

        return notes