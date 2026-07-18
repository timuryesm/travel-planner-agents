from __future__ import annotations
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, Activity


class ActivitiesAgent(BaseAgent):
    """
    Suggests things to do in one city.

    The only stage that repeats per stop, and the only one that returns a LIST
    the user multi-selects rather than a single pick. So its hints work a little
    differently from the discovery agents:

      preference_text  what the user typed on the activities stage — "lots of
                       food", "nothing too touristy". Distinct from the setup
                       preferences, which describe the whole trip; both reach
                       the prompt as separate labelled lines, never merged. The
                       merge is the mistake the adapter used to make.

      exclude          names already shown. Powers two buttons that look the
                       same from here: REGENERATE (component replaces the list)
                       and EXPAND / "show more" (component appends). Both send
                       the visible names back so the next batch is genuinely
                       different rather than a reshuffle.

      limit            how many to propose. Defaults to 10 — enough to choose
                       from without burying the user. The old code scaled this
                       to trip length (6–16); a flat, larger pool the user
                       filters is the better fit now that selection is the whole
                       interaction.

    FALLBACK KEPT, unlike CityAgent. A generic activity list is an honest answer
    the way generic countries are: four sensible things to do in any city beat a
    hard error, and activities is skippable (ActivitiesCommitData allows an
    empty list), so a degraded list is never a dead end. On a Claude failure the
    agent logs and serves the fallback rather than raising — which is why
    activities_options degrades to [] rather than 502, matching flights and
    accommodation, not country and city.

    Parsing goes through BaseAgent.ask_claude_json: prefill-free defensive parse
    plus one retry. The hand-rolled json.loads this replaced would die on a
    markdown fence and drop straight into the fallback — serving four generic
    activities while looking like it had simply found little to suggest.
    """

    name = "activities"
    DEFAULT_LIMIT = 10

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

        self.logger.info(
            f"Curating {self.limit} activities for {req.destination}"
            + (f" · excluding {len(self.exclude)} already shown" if self.exclude else "")
            + (" · stage preference given" if self.preference_text else "")
        )

        try:
            activities = self._generate_activities(req)
            self.logger.info(f"Generated {len(activities)} activities")
        except Exception as e:
            self.logger.warning(f"Activity generation failed ({e}) — using fallback")
            activities = self._fallback_activities(req)

        plan.activities = activities
        plan.mark_complete(self.name)
        return plan

    # ── Claude proposes activities ───────────────────────────────────────

    def _generate_activities(self, req) -> list[Activity]:
        # Weather context if the weather agent already ran (CLI path). In the
        # wizard, activities runs before daily_plan has a forecast, so this is
        # usually empty — the daily_plan stage is where weather actually shapes
        # the schedule.
        weather_context = ""
        # plan.weather isn't reachable from here (we only get req), and that's
        # fine: weather-aware scheduling is daily_plan's job, not this stage's.

        system_prompt = """You are a local travel expert recommending things to do in ONE city.

Return ONLY valid JSON, no markdown, no backticks, no explanation.

Structure:
{
  "activities": [
    {
      "name": "Activity name",
      "description": "One sentence on what it is and why it's worth doing",
      "estimated_cost_usd": 45.0,
      "duration_hours": 3.0,
      "category": "food|culture|outdoor|nightlife|shopping|relaxation"
    }
  ]
}

Rules:
- Propose exactly the number requested.
- Vary the list across categories and price points — not six museums.
- Mix paid and free; use 0.0 for free activities.
- Costs realistic for the city, per person.
- Always include at least one local food experience.
- category must be one of the six listed values."""

        lines = [
            f"City: {req.destination}",
            f"Trip dates: {req.departure_date} to {req.return_date}",
            f"Travelers: {req.travelers}"
            + (" (with children)" if req.with_kids else ""),
        ]

        style_line = {
            "relax": "Trip style: relaxed — favour downtime, comfort, slow experiences.",
            "active": "Trip style: active — favour movement, hiking, hands-on things.",
            "hybrid": "Trip style: a mix of activity and downtime.",
        }.get(req.travel_style)
        if style_line:
            lines.append(style_line)

        # Two preference channels, two lines — never merged.
        if req.preferences_text:
            lines.append(f'About the trip, in their own words: "{req.preferences_text}"')
        if self.preference_text:
            lines.append(
                f'What they want from activities specifically: "{self.preference_text}"'
            )

        if self.exclude:
            lines.append(
                "Already shown — propose DIFFERENT activities, not these: "
                f"{', '.join(self.exclude)}"
            )

        lines.append(f"\nPropose {self.limit} activities.")

        data = self.ask_claude_json(
            system_prompt=system_prompt,
            user_message="\n".join(lines),
        )

        activities: list[Activity] = []
        for item in data.get("activities", []):
            try:
                activities.append(Activity(
                    name=item["name"],
                    description=item["description"],
                    estimated_cost_usd=float(item["estimated_cost_usd"]),
                    duration_hours=float(item["duration_hours"]),
                    category=item.get("category", "general"),
                ))
            except (KeyError, ValueError, TypeError) as e:
                # One malformed entry shouldn't cost the rest.
                self.logger.warning(f"Skipping malformed activity: {e}")

        if not activities:
            raise ValueError("No valid activities parsed from response")

        return activities

    # ── Fallback ─────────────────────────────────────────────────────────

    def _fallback_activities(self, req) -> list[Activity]:
        """
        Generic activities if the LLM call fails.

        Respects exclude so a regenerate during an outage still changes the list
        rather than returning the same names — matches CountryAgent's fallback.
        """
        pool = [
            Activity(
                name=f"Explore {req.destination} city center",
                description="Self-guided walking tour of the main downtown sights.",
                estimated_cost_usd=0.0, duration_hours=3.0, category="culture",
            ),
            Activity(
                name="Local food market visit",
                description="Sample regional specialties at a popular local market.",
                estimated_cost_usd=30.0, duration_hours=2.0, category="food",
            ),
            Activity(
                name="Top-rated museum or landmark",
                description="Visit the destination's most famous cultural attraction.",
                estimated_cost_usd=25.0, duration_hours=2.5, category="culture",
            ),
            Activity(
                name="Evening neighborhood stroll",
                description="Explore a lively local district after dark.",
                estimated_cost_usd=0.0, duration_hours=2.0, category="nightlife",
            ),
            Activity(
                name="Half-day guided walking tour",
                description="Get oriented with a local guide covering the essential sights.",
                estimated_cost_usd=40.0, duration_hours=3.5, category="culture",
            ),
            Activity(
                name="Local cooking class",
                description="Hands-on class making a regional dish, market visit often included.",
                estimated_cost_usd=75.0, duration_hours=3.0, category="food",
            ),
            Activity(
                name="Green space or waterfront afternoon",
                description="Unwind at the city's main park, garden, or waterfront.",
                estimated_cost_usd=0.0, duration_hours=2.0, category="outdoor",
            ),
            Activity(
                name="Sunset viewpoint",
                description="Head to a well-known lookout for the end of the day.",
                estimated_cost_usd=0.0, duration_hours=1.5, category="outdoor",
            ),
        ]
        excluded = {e.lower() for e in self.exclude}
        remaining = [a for a in pool if a.name.lower() not in excluded]
        return (remaining or pool)[: self.limit]