from __future__ import annotations
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan
from src.state.schemas import City


class CityAgent(BaseAgent):
    """
    Proposes candidate cities inside the country the user already committed to.

    Reads the country from plan.request.destination — the adapter puts it there,
    the same slot the flight and hotel agents read the hub city from. The
    synthetic request has exactly one destination field and each stage fills it
    with whatever "where" means at that point in the wizard.

    One note per city, from the model:

      climate_note  What the city is like in the user's date range. Model
                    knowledge, not a forecast: Open-Meteo needs coordinates and
                    a near-term window, and neither exists here. daily_plan has
                    both and uses the real thing.

    NO safety_note, deliberately. Advisories are published per country, so the
    note already on Country covers every city inside it. A city-level safety
    field would imply a city-level signal that the feed does not publish, and
    the only way to fill it would be to ask the model — which is the exact thing
    advisory_lookup exists to prevent. City has no such field for this reason.

    Two preference channels, kept separate:

      req.preferences_text   what the user wrote at SETUP. Trip-wide, applies to
                             every stage.
      self.preference_text   what they typed on the CITY stage just now. Scoped
                             to this question.

    They are different signals and reach the prompt as different lines. Merging
    them would lose which is which — the same category of mistake as the old
    adapter shredding a sentence into `interests`.

    exclude powers regenerate: names already shown come back so the next batch
    is different rather than a reshuffle.

    NO FALLBACK, unlike CountryAgent. There is no honest generic answer to
    "cities in $COUNTRY" without the model. A hardcoded map would cover the
    eight countries in CountryAgent's fallback pool and nothing else, and
    inventing city names and climate notes for the rest is precisely what this
    codebase keeps deciding not to do. ask_claude_json retries once for a
    formatting slip; past that, this raises and the caller gets an honest
    failure instead of a fiction.
    """

    name = "city"
    DEFAULT_LIMIT = 6

    def __init__(
        self,
        exclude: list[str] | None = None,
        limit: int | None = None,
        preference_text: str | None = None,
    ):
        super().__init__()
        self.exclude = exclude or []
        self.limit = limit or self.DEFAULT_LIMIT
        self.preference_text = preference_text

    def run(self, plan: TravelPlan) -> TravelPlan:
        req = plan.request
        country = (req.destination or "").strip()

        if not country:
            # Not recoverable and not the model's fault: the wizard reached the
            # city stage without a committed country, which means the state
            # machine or the adapter is wrong. Fail loudly rather than ask
            # Claude for cities in "". The route's own guard should catch this
            # first and 409; this is the backstop.
            raise ValueError(
                "CityAgent needs a country in request.destination — the country "
                "commit is missing or the adapter did not pass it through"
            )

        self.logger.info(
            f"Proposing {self.limit} cities in {country} · "
            f"{req.departure_date} to {req.return_date} · {req.travelers} "
            f"traveller(s){' with kids' if req.with_kids else ''} · "
            f"style={req.travel_style}"
            + (f" · excluding {len(self.exclude)} already seen" if self.exclude else "")
            + (" · stage preference given" if self.preference_text else "")
        )

        cities = self._propose_cities(req, country)
        self.logger.info(f"Claude proposed {len(cities)} cities in {country}")

        plan.proposed_cities = cities
        plan.mark_complete(self.name)
        return plan

    # ── Claude proposes cities ───────────────────────────────────────────

    def _propose_cities(self, req, country: str) -> list[City]:
        system_prompt = """You are a travel advisor recommending CITIES within one country.

Return ONLY valid JSON, no markdown, no backticks, no explanation.

Structure:
{
  "cities": [
    {
      "city": "City name",
      "why_chosen_summary": "Two or three sentences on why this city fits this specific traveler — reference their budget, style, dates, and who they're travelling with.",
      "climate_note": "What the weather is typically like in this city during their travel dates, and what that means for the trip."
    }
  ]
}

Rules:
- Every city must be inside the country given. Nothing across a border.
- Propose exactly the number of cities requested.
- The traveler picks ONE city as their base and stays there the whole trip.
  They may add others as DAY TRIPS out and back — no overnight stays
  elsewhere. So favour cities that either make a good base, or sit close
  enough to a plausible base for a day trip.
- Vary the list: a capital, a second city, somewhere smaller or coastal or
  mountainous. Do not propose six neighbourhoods of one idea.
- climate_note is the TYPICAL climate in their date range, not a forecast.
  Be concrete: temperatures, rain, season. Cities in one country can differ
  sharply — say so where it matters.
- Do NOT mention safety, crime, political stability, or travel advisories.
  A live government advisory is already attached at the country level and
  covers every city here. Anything you write about safety would be
  discarded — or worse, contradict it."""

        kids_line = (
            "Travelling with children — favour cities that are easy with kids."
            if req.with_kids
            else "No children on this trip."
        )
        style_line = {
            "relax": "Trip style: relaxed. Slow pace, comfort, downtime.",
            "active": "Trip style: active. Hiking, adventure, being on the move.",
            "hybrid": "Trip style: a mix of activity and downtime.",
        }.get(req.travel_style, "Trip style: a mix of activity and downtime.")

        lines = [
            f"Country (already chosen): {country}",
            f"Departing from: {req.origin}",
            f"Travel dates: {req.departure_date} to {req.return_date}",
            f"Budget (total, USD): {req.budget_usd:,.0f}",
            f"Travelers: {req.travelers}",
            kids_line,
            style_line,
        ]

        # Two channels, two lines. The setup text describes the trip; the stage
        # text answers this question. Both verbatim — the user wrote sentences,
        # they go in as sentences.
        if req.preferences_text:
            lines.append(f'About the trip, in their own words: "{req.preferences_text}"')
        if self.preference_text:
            lines.append(
                f'What they want from the city specifically: "{self.preference_text}"'
            )

        if self.exclude:
            lines.append(
                f"Already suggested — propose DIFFERENT cities, not these: "
                f"{', '.join(self.exclude)}"
            )
        lines.append(f"\nPropose {self.limit} cities in {country} that fit.")

        data = self.ask_claude_json(
            system_prompt=system_prompt,
            user_message="\n".join(lines),
        )

        cities: list[City] = []
        for item in data.get("cities", []):
            try:
                cities.append(City(
                    city=item["city"],
                    why_chosen_summary=item["why_chosen_summary"],
                    climate_note=item["climate_note"],
                ))
            except (KeyError, TypeError) as e:
                # One malformed entry shouldn't cost the other five. Follows
                # ActivitiesAgent's pattern.
                self.logger.warning(f"Skipping malformed city: {e}")

        if not cities:
            raise ValueError("No valid cities parsed from response")

        return cities