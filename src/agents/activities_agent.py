from __future__ import annotations
import json
import anthropic
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, Activity
from src.config.settings import settings


class ActivitiesAgent(BaseAgent):

    name = "activities"
    MODEL = "claude-sonnet-4-6"

    def run(self, plan: TravelPlan) -> TravelPlan:
        req = plan.request

        self.logger.info(
            f"Curating activities for {req.destination} · "
            f"interests: {', '.join(req.interests) or 'general'}"
        )

        # Build weather context if the weather agent already ran
        weather_context = ""
        if plan.weather:
            sample = list(plan.weather.forecast_by_day.values())[:3]
            weather_context = (
                f"\nExpected weather: {', '.join(sample)}. "
                f"Factor this into indoor/outdoor recommendations."
            )

        try:
            activities = self._generate_activities(req, weather_context)
            self.logger.info(f"Generated {len(activities)} activities")
        except Exception as e:
            self.logger.warning(f"Activity generation failed ({e}) — using fallback")
            activities = self._fallback_activities(req)

        plan.activities = activities
        plan.mark_complete(self.name)
        return plan

    # ── Claude as the tool ───────────────────────────────────────────────

    def _generate_activities(self, req, weather_context: str) -> list[Activity]:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        nights = (req.return_date - req.departure_date).days
        # Roughly 2 activities per day
        target_count = max(6, min(nights * 2, 16))

        system_prompt = """You are a local travel expert creating activity recommendations.
Return ONLY valid JSON, no markdown, no backticks, no explanation.

Each activity must match this exact structure:
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

Make costs realistic for the destination. Use 0.0 for free activities."""

        user_message = f"""Destination: {req.destination}
Trip length: {nights} days
Traveler interests: {', '.join(req.interests) if req.interests else 'general sightseeing'}
Number of travelers: {req.travelers}{weather_context}

Generate {target_count} diverse activities matching the traveler's interests.
Mix paid and free options. Include local food experiences."""

        response = client.messages.create(
            model=self.MODEL,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text
        data = json.loads(raw)

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
            except (KeyError, ValueError) as e:
                self.logger.warning(f"Skipping malformed activity: {e}")

        if not activities:
            raise ValueError("No valid activities parsed from response")

        return activities

    # ── Fallback ─────────────────────────────────────────────────────────

    def _fallback_activities(self, req) -> list[Activity]:
        """Generic activities used if the LLM call fails."""
        return [
            Activity(
                name=f"Explore {req.destination} city center",
                description="Self-guided walking tour of the main downtown sights.",
                estimated_cost_usd=0.0,
                duration_hours=3.0,
                category="culture",
            ),
            Activity(
                name="Local food market visit",
                description="Sample regional specialties at a popular local market.",
                estimated_cost_usd=30.0,
                duration_hours=2.0,
                category="food",
            ),
            Activity(
                name="Top-rated museum or landmark",
                description="Visit the destination's most famous cultural attraction.",
                estimated_cost_usd=25.0,
                duration_hours=2.5,
                category="culture",
            ),
            Activity(
                name="Evening neighborhood stroll",
                description="Explore a lively local district after dark.",
                estimated_cost_usd=0.0,
                duration_hours=2.0,
                category="nightlife",
            ),
        ]