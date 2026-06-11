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
        """Ask Claude to write the final itinerary from all agent results."""

        context = f"""You are writing a final travel itinerary based on research from specialist agents.

Travel request:
- From: {plan.request.origin} to {plan.request.destination}
- Dates: {plan.request.departure_date} → {plan.request.return_date}
- Travelers: {plan.request.travelers}
- Budget: ${plan.request.budget_usd:,.0f} USD

Agent results:
"""
        if plan.selected_flight:
            f = plan.selected_flight
            context += f"\nFLIGHT: {f.airline}, departs {f.departure_time}, arrives {f.arrival_time}, ${f.price_usd:.0f}"

        if plan.selected_hotel:
            h = plan.selected_hotel
            context += f"\nHOTEL: {h.name} ({h.stars}★), ${h.price_per_night_usd:.0f}/night, total ${h.total_price_usd:.0f}"

        if plan.activities:
            context += f"\nACTIVITIES:\n"
            for a in plan.activities:
                context += f"  - {a.name}: {a.description} (${a.estimated_cost_usd:.0f}, {a.duration_hours}h)\n"

        if plan.weather:
            context += f"\nWEATHER: {plan.weather.forecast_by_day}"
            context += f"\nPACKING TIPS: {', '.join(plan.weather.packing_tips)}"

        if plan.budget:
            b = plan.budget
            context += f"\nBUDGET: Flights ${b.flights_usd:.0f} + Hotel ${b.hotel_usd:.0f} + Activities ${b.activities_usd:.0f} = Total ${b.total_usd:.0f}"
            context += f"\nWithin budget: {'Yes' if b.within_budget else 'No'}"

        context += "\n\nWrite a friendly, day-by-day markdown itinerary with a budget summary table at the end."

        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": context}]
        )

        return response.content[0].text