from datetime import date
from unittest.mock import patch, MagicMock
from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.activities_agent import ActivitiesAgent


def make_plan():
    return TravelPlan(
        request=TravelRequest(
            destination="Tokyo", origin="Toronto",
            departure_date=date(2026, 8, 1), return_date=date(2026, 8, 10),
            budget_usd=4000.0, travelers=1, interests=["food", "temples"],
        )
    )


MOCK_CLAUDE_RESPONSE = """{
  "activities": [
    {"name": "Tsukiji Market", "description": "Fresh sushi breakfast.",
     "estimated_cost_usd": 40.0, "duration_hours": 2.0, "category": "food"},
    {"name": "Senso-ji Temple", "description": "Historic Buddhist temple.",
     "estimated_cost_usd": 0.0, "duration_hours": 1.5, "category": "culture"}
  ]
}"""


def test_activities_agent_parses_claude_response():
    agent = ActivitiesAgent()
    plan  = make_plan()

    with patch.object(agent, "_generate_activities") as mock_gen:
        from src.state.travel_plan import Activity
        mock_gen.return_value = [
            Activity(name="Tsukiji Market", description="Sushi",
                     estimated_cost_usd=40.0, duration_hours=2.0, category="food"),
            Activity(name="Senso-ji", description="Temple",
                     estimated_cost_usd=0.0, duration_hours=1.5, category="culture"),
        ]
        result = agent.safe_run(plan)

    assert result.activities is not None
    assert len(result.activities) == 2
    assert "activities" in result.completed_agents


def test_activities_fallback_on_failure():
    agent = ActivitiesAgent()
    plan  = make_plan()

    with patch.object(agent, "_generate_activities", side_effect=Exception("API down")):
        result = agent.safe_run(plan)

    # Fallback should still produce activities
    assert result.activities is not None
    assert len(result.activities) > 0
    assert "activities" in result.completed_agents


def test_activities_real_parse_logic():
    """Test the actual JSON parsing with a mocked Claude client."""
    agent = ActivitiesAgent()
    plan  = make_plan()

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=MOCK_CLAUDE_RESPONSE)]

    with patch("src.agents.activities_agent.anthropic.Anthropic") as mock_anthropic:
        mock_anthropic.return_value.messages.create.return_value = mock_response
        result = agent.safe_run(plan)

    assert len(result.activities) == 2
    assert result.activities[0].name == "Tsukiji Market"
    assert result.activities[1].estimated_cost_usd == 0.0