from datetime import date
from unittest.mock import MagicMock, patch
from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.orchestrator import Orchestrator, ExecutionPlan


def make_plan():
    return TravelPlan(
        request=TravelRequest(
            destination="Tokyo",
            origin="Toronto",
            departure_date=date(2025, 8, 1),
            return_date=date(2025, 8, 10),
            budget_usd=4000.0,
        )
    )


def test_execution_plan_has_all_agents():
    """Orchestrator plan must include all five agents."""
    plan = make_plan()
    orchestrator = Orchestrator()

    with patch.object(orchestrator.client.messages, "create") as mock_create:
        mock_create.return_value = MagicMock(
            content=[MagicMock(text="""{
                "tasks": [
                    {"agent": "weather",    "reason": "forecasts", "depends_on": []},
                    {"agent": "flights",    "reason": "transport",  "depends_on": []},
                    {"agent": "hotels",     "reason": "stay",       "depends_on": []},
                    {"agent": "activities", "reason": "fun",        "depends_on": ["weather"]},
                    {"agent": "budget",     "reason": "costs",      "depends_on": ["flights","hotels","activities"]}
                ],
                "strategy_notes": "Standard plan."
            }""")]
        )
        execution_plan = orchestrator.create_plan(plan)

    agents = [t.agent for t in execution_plan.tasks]
    assert "weather"    in agents
    assert "flights"    in agents
    assert "hotels"     in agents
    assert "activities" in agents
    assert "budget"     in agents


def test_budget_runs_last():
    """Budget agent must depend on the other three agents."""
    plan = make_plan()
    orchestrator = Orchestrator()

    with patch.object(orchestrator.client.messages, "create") as mock_create:
        mock_create.return_value = MagicMock(
            content=[MagicMock(text="""{
                "tasks": [
                    {"agent": "weather",    "reason": "forecasts", "depends_on": []},
                    {"agent": "flights",    "reason": "transport",  "depends_on": []},
                    {"agent": "hotels",     "reason": "stay",       "depends_on": []},
                    {"agent": "activities", "reason": "fun",        "depends_on": ["weather"]},
                    {"agent": "budget",     "reason": "costs",      "depends_on": ["flights","hotels","activities"]}
                ],
                "strategy_notes": "Standard plan."
            }""")]
        )
        execution_plan = orchestrator.create_plan(plan)

    budget_task = next(t for t in execution_plan.tasks if t.agent == "budget")
    assert "flights"    in budget_task.depends_on
    assert "hotels"     in budget_task.depends_on
    assert "activities" in budget_task.depends_on


def test_fallback_plan_on_bad_json():
    """Orchestrator should return a valid fallback if Claude returns bad JSON."""
    plan = make_plan()
    orchestrator = Orchestrator()

    with patch.object(orchestrator.client.messages, "create") as mock_create:
        mock_create.return_value = MagicMock(
            content=[MagicMock(text="this is not json at all")]
        )
        execution_plan = orchestrator.create_plan(plan)

    assert isinstance(execution_plan, ExecutionPlan)
    assert len(execution_plan.tasks) == 5