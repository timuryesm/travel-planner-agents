from __future__ import annotations
import json
import anthropic
import logging
from pydantic import BaseModel
from src.state.travel_plan import TravelPlan, TravelRequest
from src.config.settings import settings


# ── What the LLM returns as a plan ──────────────────────────────────────────

class AgentTask(BaseModel):
    agent: str           # "weather" | "flights" | "hotels" | "activities" | "budget"
    reason: str          # why this agent is needed
    depends_on: list[str] = []   # agents that must complete first


class ExecutionPlan(BaseModel):
    tasks: list[AgentTask]
    strategy_notes: str  # orchestrator's plain-English reasoning


# ── The orchestrator ─────────────────────────────────────────────────────────

class Orchestrator:
    MODEL = "claude-sonnet-4-6"

    PLANNING_PROMPT = """You are the orchestrator of a multi-agent travel planning system.

Given a travel request, produce an execution plan listing which specialist agents
to invoke and in what order.

Available agents:
- weather     : fetches forecasts and packing tips for the travel dates
- flights     : searches for flight options and prices
- hotels      : searches for accommodation options and prices
- activities  : curates local experiences based on traveler interests
- budget      : aggregates all costs and checks against the user's budget

Rules:
- budget must always run last (it depends on all others)
- weather can always run first (no dependencies)
- flights and hotels have no dependencies on each other
- activities should run after weather (weather affects recommendations)

Respond with ONLY valid JSON. No markdown, no backticks, no explanation. Raw JSON only:
{
  "tasks": [
    {
      "agent": "weather",
      "reason": "short explanation",
      "depends_on": []
    }
  ],
  "strategy_notes": "brief plain-english summary of the approach"
}"""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.logger = logging.getLogger(self.__class__.__name__)

    def create_plan(self, plan: TravelPlan) -> ExecutionPlan:
        """Ask Claude to produce a structured execution plan for this travel request."""

        user_message = f"""Travel request:
- From: {plan.request.origin}
- To: {plan.request.destination}
- Dates: {plan.request.departure_date} → {plan.request.return_date}
- Budget: ${plan.request.budget_usd:,.0f} USD
- Travelers: {plan.request.travelers}
- Interests: {', '.join(plan.request.interests) if plan.request.interests else 'not specified'}

Produce the execution plan."""

        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=1024,
            system=self.PLANNING_PROMPT,
            messages=[{"role": "user", "content": user_message}]
        )

        raw = response.content[0].text
        self.logger.info(f"Raw plan response: {repr(raw[:200])}")

        try:
            data = json.loads(raw)
            return ExecutionPlan(**data)
        except (json.JSONDecodeError, Exception) as e:
            plan.add_error("orchestrator", f"Failed to parse execution plan: {e}")
            # Fallback: return a sensible default plan
            return ExecutionPlan(
                tasks=[
                    AgentTask(agent="weather",    reason="Always useful",          depends_on=[]),
                    AgentTask(agent="flights",    reason="Core travel component",  depends_on=[]),
                    AgentTask(agent="hotels",     reason="Core travel component",  depends_on=[]),
                    AgentTask(agent="activities", reason="Enrich the itinerary",   depends_on=["weather"]),
                    AgentTask(agent="budget",     reason="Summarise all costs",    depends_on=["flights","hotels","activities"]),
                ],
                strategy_notes="Fallback plan used due to parsing error."
            )

    def assemble_itinerary(self, plan: TravelPlan) -> str:
        """
        Take the fully-populated TravelPlan and ask Claude to write
        a polished, day-by-day markdown itinerary.
        """
        self.logger.info("Assembling final itinerary")

        context = self._build_context(plan)

        system_prompt = """You are an expert travel planner writing a final itinerary document.

You will receive structured research from specialist agents (flights, hotel,
weather, activities, budget). Write a warm, well-organized, day-by-day travel
itinerary in markdown.

Structure your response as:
1. A short, friendly intro paragraph (2-3 sentences) about the trip
2. A "Getting There" section with the flight details
3. A "Where You'll Stay" section with the accommodation
4. A "Day-by-Day Plan" section — distribute the activities sensibly across the
   available days, accounting for the weather each day. Put outdoor activities
   on better-weather days. Don't overload any single day (2-3 activities max).
5. A "Budget Summary" section with the cost breakdown as a markdown table
6. A "Packing Tips" section from the weather data

Be specific and practical. Reference actual prices, times, and forecasts from
the data. Write in a friendly second-person voice ("you'll arrive...").
Do not invent details that aren't in the data."""

        client = self.client
        response = client.messages.create(
            model=self.MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": context}],
        )

        itinerary = response.content[0].text
        plan.itinerary_markdown = itinerary
        self.logger.info(f"Itinerary assembled ({len(itinerary)} chars)")
        return itinerary


    def _build_context(self, plan: TravelPlan) -> str:
        """Format all agent results into a single text block for Claude."""
        req = plan.request
        nights = (req.return_date - req.departure_date).days

        lines = [
            f"TRIP REQUEST",
            f"From: {req.origin} to {req.destination}",
            f"Dates: {req.departure_date} to {req.return_date} ({nights} nights)",
            f"Travelers: {req.travelers}",
            f"Budget: ${req.budget_usd:,.0f} USD",
            f"Interests: {', '.join(req.interests) if req.interests else 'general'}",
            "",
        ]

        # ── Flight ───────────────────────────────────────────────────────
        if plan.selected_flight:
            f = plan.selected_flight
            lines.append("FLIGHT (selected best option):")
            lines.append(f"  Trip type: {f.trip_type}")
            for i, leg in enumerate(f.legs, 1):
                lines.append(
                    f"  Leg {i}: {leg.airline}, {leg.origin} → {leg.destination}, "
                    f"departs {leg.departure_time}, arrives {leg.arrival_time}, "
                    f"{leg.duration_hours}h"
                )
            lines.append(f"  Total price: ${f.price_usd:,.2f}")
            if f.booking_url:
                lines.append(f"  Booking link: {f.booking_url}")
            lines.append("")

        # ── Hotel ────────────────────────────────────────────────────────
        if plan.selected_hotel:
            h = plan.selected_hotel
            lines.append("ACCOMMODATION (selected best option):")
            lines.append(f"  {h.name} ({h.property_type}, via {h.provider})")
            lines.append(f"  Location: {h.location}")
            if h.stars:
                lines.append(f"  Rating: {h.stars} stars")
            lines.append(
                f"  ${h.price_per_night_usd:,.2f}/night, "
                f"total ${h.total_price_usd:,.2f} for {nights} nights"
            )
            if h.booking_url:
                lines.append(f"  Booking link: {h.booking_url}")
            lines.append("")

        # ── Weather ──────────────────────────────────────────────────────
        if plan.weather:
            lines.append("WEATHER FORECAST (by day):")
            for day, forecast in plan.weather.forecast_by_day.items():
                lines.append(f"  {day}: {forecast}")
            lines.append("  Packing tips: " + "; ".join(plan.weather.packing_tips))
            lines.append("")

        # ── Activities ───────────────────────────────────────────────────
        if plan.activities:
            lines.append(f"AVAILABLE ACTIVITIES ({len(plan.activities)} options):")
            for a in plan.activities:
                cost = "Free" if a.estimated_cost_usd == 0 else f"${a.estimated_cost_usd:,.0f}"
                lines.append(
                    f"  - {a.name} [{a.category}]: {a.description} "
                    f"({cost}, {a.duration_hours}h)"
                )
            lines.append("")

        # ── Committed day-by-day (wizard path) ───────────────────────────
        # When the wizard has already arranged activities into days, that plan
        # is authoritative — the user may have reordered it. Give Claude the
        # exact structure to render rather than asking it to re-distribute.
        # The CLI path has no day_by_day and falls through to the instruction
        # below, which asks for a fresh distribution.
        day_by_day = getattr(plan, "day_by_day", None)
        if day_by_day:
            lines.append("PLANNED DAYS (already arranged — render these as-is):")
            for d in day_by_day:
                names = ", ".join(d.activity_names) if d.activity_names else "open day"
                weather = f" — {d.weather_line}" if d.weather_line else ""
                lines.append(f"  {d.date} ({d.city}){weather}: {names}")
            lines.append("")

        # ── Budget ───────────────────────────────────────────────────────
        if plan.budget:
            b = plan.budget
            lines.append("BUDGET BREAKDOWN:")
            lines.append(f"  Flights: ${b.flights_usd:,.2f}")
            lines.append(f"  Accommodation: ${b.hotel_usd:,.2f}")
            lines.append(f"  Activities: ${b.activities_usd:,.2f}")
            lines.append(f"  Miscellaneous: ${b.miscellaneous_usd:,.2f}")
            lines.append(f"  TOTAL: ${b.total_usd:,.2f} (budget ${req.budget_usd:,.0f})")
            lines.append(f"  Within budget: {'Yes' if b.within_budget else 'No'}")
            lines.append("")

        if getattr(plan, "day_by_day", None):
            lines.append(
                "Now write the complete itinerary following your structure. The "
                "days are already arranged above — render them in that order, "
                "adding your prose, prices and weather notes. Do not reorder or "
                "re-distribute the activities."
            )
        else:
            lines.append(
                "Now write the complete day-by-day itinerary following the "
                f"structure in your instructions. Distribute activities across the "
                f"{nights} days, matching outdoor activities to good-weather days."
            )

        return "\n".join(lines)