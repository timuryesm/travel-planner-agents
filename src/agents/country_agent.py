from __future__ import annotations
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan
from src.state.schemas import Country
from src.tools.advisory_lookup import advisory_note


class CountryAgent(BaseAgent):
    """
    Proposes candidate countries from the user's setup, then attaches a LIVE
    travel-advisory safety signal to each.

    Two notes per country, from two deliberately different sources:

      climate_note  from the model. What October is like in Japan does not
                    change year to year, so this is stable knowledge rather
                    than a forecast. There is also no forecast to be had here:
                    Open-Meteo needs coordinates, and at country-selection time
                    no city has been chosen. The daily_plan stage, which has
                    both a city and dates, uses the real forecast.

      safety_note   from the U.S. State Department advisory feed, never from
                    the model. Advisories change, and stale or invented safety
                    guidance is worse than none. On lookup failure the claim is
                    dropped rather than guessed.

    Contract matches every other agent: run(plan) reads plan.request, writes
    results back onto the plan — specifically plan.proposed_countries, declared
    on TravelPlan alongside the other agents' result fields.

    exclude powers the regenerate button: names already shown are passed back so
    the next batch is different rather than a reshuffle of the same six.

    The fallback pool is a real answer, not a fiction: eight countries that suit
    most travellers, honestly generic rather than falsely tailored. It exists
    because a country list is the wizard's first step and an empty one is a dead
    end. Note what it costs, though — when it fires, the user gets suggestions
    that ignore everything they typed, and only the WARNING line says so.
    ask_claude_json's retry exists to keep that path rare: it used to trigger on
    a mere markdown fence.
    """

    name = "country"
    DEFAULT_LIMIT = 6

    def __init__(self, exclude: list[str] | None = None, limit: int | None = None):
        super().__init__()
        self.exclude = exclude or []
        self.limit = limit or self.DEFAULT_LIMIT

    def run(self, plan: TravelPlan) -> TravelPlan:
        req = plan.request

        self.logger.info(
            f"Proposing {self.limit} countries · {req.departure_date} to "
            f"{req.return_date} · ${req.budget_usd:,.0f} · {req.travelers} "
            f"traveller(s){' with kids' if req.with_kids else ''} · "
            f"style={req.travel_style}"
            + (f" · excluding {len(self.exclude)} already seen" if self.exclude else "")
        )

        try:
            candidates = self._propose_countries(req)
            self.logger.info(f"Claude proposed {len(candidates)} countries")
        except Exception as e:
            self.logger.warning(f"Country discovery failed ({e}) — using fallback")
            candidates = self._fallback_countries()

        # Attach a live safety signal to each candidate. Every lookup hits the
        # same cached feed — one HTTP request at most for the whole batch, not
        # one per country. See tools/advisory_lookup.py for why that matters.
        countries: list[Country] = []
        unresolved = 0
        for c in candidates:
            name = c.get("name", "")
            note = advisory_note(name)
            if note is None:
                unresolved += 1
            countries.append(Country(
                name=name,
                why_chosen_summary=c["why_chosen_summary"],
                climate_note=c["climate_note"],
                # Live signal replaces whatever the model might have guessed
                safety_note=note or "Check current travel advisories before booking.",
            ))

        if unresolved:
            self.logger.warning(
                f"{unresolved}/{len(countries)} countries have no live advisory "
                f"— using neutral placeholder"
            )

        plan.proposed_countries = countries
        plan.mark_complete(self.name)
        return plan

    # ── Claude proposes countries ────────────────────────────────────────

    def _propose_countries(self, req) -> list[dict]:
        system_prompt = """You are a travel destination advisor recommending COUNTRIES.

Return ONLY valid JSON, no markdown, no backticks, no explanation.

Structure:
{
  "countries": [
    {
      "name": "Country name",
      "why_chosen_summary": "Two or three sentences on why this country fits this specific traveler — reference their budget, style, and who they're travelling with.",
      "climate_note": "What the weather is typically like there during their travel dates, and what that means for the trip."
    }
  ]
}

Rules:
- Propose exactly the number of countries requested.
- Vary regions and price levels. Do not propose six variations of one idea.
- The traveler picks ONE country and visits cities within it, so favour
  countries with several places worth visiting.
- climate_note is about the TYPICAL climate in their date range, not a
  forecast. Be concrete: temperatures, rain, season.
- Do NOT mention safety, crime, political stability, or travel advisories.
  A live government advisory is attached to each country after you respond,
  and anything you write about safety would be discarded — or worse, contradict it."""

        kids_line = (
            "Travelling with children — favour countries that are easy with kids."
            if req.with_kids
            else "No children on this trip."
        )
        style_line = {
            "relax": "Trip style: relaxed. Slow pace, comfort, downtime.",
            "active": "Trip style: active. Hiking, adventure, being on the move.",
            "hybrid": "Trip style: a mix of activity and downtime.",
        }.get(req.travel_style, "Trip style: a mix of activity and downtime.")

        lines = [
            f"Departing from: {req.origin}",
            f"Travel dates: {req.departure_date} to {req.return_date}",
            f"Budget (total, USD): {req.budget_usd:,.0f}",
            f"Travelers: {req.travelers}",
            kids_line,
            style_line,
        ]
        if req.interests:
            lines.append(f"Interests: {', '.join(req.interests)}")
        if req.preferences_text:
            # Verbatim. The user wrote a sentence; it goes in as a sentence.
            lines.append(f'In their own words: "{req.preferences_text}"')
        if self.exclude:
            lines.append(
                f"Already suggested — propose DIFFERENT countries, not these: "
                f"{', '.join(self.exclude)}"
            )
        lines.append(f"\nPropose {self.limit} countries that fit.")

        data = self.ask_claude_json(
            system_prompt=system_prompt,
            user_message="\n".join(lines),
        )

        countries = data.get("countries", [])
        if not countries:
            raise ValueError("No countries parsed from response")
        return countries

    # ── Fallback ─────────────────────────────────────────────────────────

    def _fallback_countries(self) -> list[dict]:
        """
        Generic well-rounded countries if the LLM call fails.

        Respects exclude so that a regenerate during an outage still changes the
        list instead of returning the same six names again.
        """
        pool = [
            {"name": "Portugal",
             "why_chosen_summary": "Mild weather, walkable cities, and some of the best value dining in Western Europe.",
             "climate_note": "Spring and early autumn are ideal — warm days, few crowds."},
            {"name": "Japan",
             "why_chosen_summary": "Temples, mountains and a food culture that rewards wandering, with superb rail links between cities.",
             "climate_note": "Cherry blossom in early April; autumn foliage late November. Summers are hot and humid."},
            {"name": "Mexico",
             "why_chosen_summary": "World-class museums, a defining food scene, and coastline within reach of the capital.",
             "climate_note": "Dry season November–April brings clear skies and comfortable temperatures."},
            {"name": "Iceland",
             "why_chosen_summary": "Glaciers, geysers and northern lights within an hour of leaving the capital.",
             "climate_note": "September–March for aurora; June–August for midnight sun and hiking."},
            {"name": "Italy",
             "why_chosen_summary": "Cities that reward slow walking, and enough regional variety to fill a fortnight.",
             "climate_note": "May–June and September avoid the August heat and crowds."},
            {"name": "South Korea",
             "why_chosen_summary": "Palaces beside skyscrapers, 24-hour markets, and the best public transit of any megacity.",
             "climate_note": "April–June and September–November avoid the humid summer and cold winter."},
            {"name": "Spain",
             "why_chosen_summary": "Distinct regions, late dinners, and cheap fast trains between them.",
             "climate_note": "Spring and autumn are comfortable; inland summers are punishing."},
            {"name": "Vietnam",
             "why_chosen_summary": "Long coastline, dense street-food culture, and a favourable exchange rate.",
             "climate_note": "Climate varies sharply north to south; the north is cool and dry December–February."},
        ]
        excluded = {e.lower() for e in self.exclude}
        remaining = [c for c in pool if c["name"].lower() not in excluded]
        return (remaining or pool)[: self.limit]