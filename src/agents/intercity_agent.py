from __future__ import annotations
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, IntercityOption


class IntercityAgent(BaseAgent):
    """
    Proposes ways to get from the hub city to ONE spoke city and back — a day
    trip out and back the same trip, no overnight.

    Called per spoke, like ActivitiesAgent is called per stop: the intercity
    stage runs it once for each spoke to fill that spoke's option list, and the
    user picks one option plus the travel dates.

    There is no booking API for "trains from Tokyo to Nara and what they cost",
    so this comes from the model, not a provider. That has a consequence the
    schema is explicit about: the numbers are INDICATIVE, not quotes. cost_usd
    is an estimate, duration is typical, and — in this version — sources is
    empty because there is no web search yet.

    On the sources field: it stays [] here, never fabricated. Option B (this
    version) is model knowledge only; the web-search-with-citations upgrade is a
    later step and drops into this same agent without the stage changing. An
    invented citation would be worse than none — the same principle as
    advisory_note refusing to guess. When search lands, real Citations fill this.

    Reads the hub from plan.request.destination and the spoke from the
    constructor: the adapter builds a synthetic request whose destination is the
    hub, and passes the target spoke separately, because "from where" and "to
    where" are different questions.

    Degrades to a small fallback on failure, like activities — an intercity list
    is skippable-ish (the user still gets the trip), and a generic "train,
    ~2h, ~$40" beats a hard error.
    """

    name = "intercity"
    DEFAULT_LIMIT = 3

    def __init__(self, spoke_city: str, limit: int | None = None):
        super().__init__()
        self.spoke_city = spoke_city
        self.limit = limit or self.DEFAULT_LIMIT

    def run(self, plan: TravelPlan) -> TravelPlan:
        req = plan.request
        hub = (req.destination or "").strip()

        if not hub or not self.spoke_city:
            raise ValueError(
                "IntercityAgent needs both a hub (request.destination) and a "
                "spoke city — one is missing"
            )

        self.logger.info(f"Finding routes: {hub} → {self.spoke_city} (day trip)")

        try:
            options = self._propose_routes(req, hub)
            self.logger.info(
                f"Proposed {len(options)} routes {hub} → {self.spoke_city}"
            )
        except Exception as e:
            self.logger.warning(f"Route proposal failed ({e}) — using fallback")
            options = self._fallback_routes()

        plan.intercity_options = options
        plan.mark_complete(self.name)
        return plan

    # ── Claude proposes routes ───────────────────────────────────────────

    def _propose_routes(self, req, hub: str) -> list[IntercityOption]:
        system_prompt = """You are a travel logistics expert planning a DAY TRIP: out from a
base city to a nearby city and back the same day, no overnight stay.

Return ONLY valid JSON, no markdown, no backticks, no explanation.

Structure:
{
  "options": [
    {
      "mode": "train|bus|flight|ferry|car",
      "description": "One sentence: the route, roughly how it works, why you'd pick it.",
      "duration_hours": 1.5,
      "cost_usd": 40.0
    }
  ]
}

Rules:
- Propose exactly the number of options requested, genuinely different modes or
  routes where the geography allows — not three near-identical trains.
- duration_hours is ONE WAY, typical door-to-station-to-door.
- cost_usd is PER PERSON, ROUND TRIP, in USD. An estimate — say a realistic
  typical fare, not a precise quote.
- Only propose a mode if it's actually plausible for a same-day round trip at
  this distance. If the cities are far apart, a day trip may only make sense by
  fast train or flight; don't invent a 9-hour bus as a "day trip".
- Do NOT invent booking links, schedules, or citations. Just the estimate."""

        style = {
            "relax": "The traveler prefers comfort and simplicity over saving money.",
            "active": "The traveler is happy with efficient, no-frills transport.",
            "hybrid": "The traveler wants a sensible balance of cost and comfort.",
        }.get(req.travel_style, "")

        lines = [
            f"From (base city): {hub}",
            f"To (day-trip city): {self.spoke_city}",
            f"Travelers: {req.travelers}"
            + (" (with children)" if req.with_kids else ""),
        ]
        if style:
            lines.append(style)
        lines.append(
            f"\nPropose {self.limit} ways to make this day trip out and back."
        )

        data = self.ask_claude_json(
            system_prompt=system_prompt,
            user_message="\n".join(lines),
        )

        options: list[IntercityOption] = []
        for item in data.get("options", []):
            try:
                options.append(IntercityOption(
                    mode=item["mode"],
                    description=item["description"],
                    duration_hours=float(item["duration_hours"]),
                    cost_usd=float(item["cost_usd"]),
                    sources=[],   # Option B: model knowledge, no web search yet
                ))
            except (KeyError, ValueError, TypeError) as e:
                self.logger.warning(f"Skipping malformed route: {e}")

        if not options:
            raise ValueError("No valid routes parsed from response")

        return options

    # ── Fallback ─────────────────────────────────────────────────────────

    def _fallback_routes(self) -> list[IntercityOption]:
        """
        Generic day-trip options if the model call fails. Deliberately vague on
        cost/time because we no longer know the distance — honest placeholders,
        not confident numbers. sources stays empty.
        """
        return [
            IntercityOption(
                mode="train",
                description=f"Take a regional train to {self.spoke_city} and back — usually the simplest day trip.",
                duration_hours=2.0, cost_usd=40.0, sources=[],
            ),
            IntercityOption(
                mode="bus",
                description=f"Intercity bus to {self.spoke_city} — slower but typically the cheapest option.",
                duration_hours=3.0, cost_usd=20.0, sources=[],
            ),
        ][: self.limit]