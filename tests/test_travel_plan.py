from datetime import date
from src.state.travel_plan import TravelPlan, TravelRequest, FlightOption

def test_travel_plan_creation():
    plan = TravelPlan(
        request=TravelRequest(
            destination="Tokyo",
            origin="Toronto",
            departure_date=date(2025, 8, 1),
            return_date=date(2025, 8, 10),
            budget_usd=4000.0,
            travelers=1,
            interests=["food", "temples", "hiking"]
        )
    )
    assert plan.flight_options is None        # empty at start
    assert plan.completed_agents == []        # nothing done yet
    assert plan.is_ready_for_output() is False

def test_mark_complete():
    plan = TravelPlan(
        request=TravelRequest(
            destination="Tokyo",
            origin="Toronto",
            departure_date=date(2025, 8, 1),
            return_date=date(2025, 8, 10),
            budget_usd=4000.0,
        )
    )
    for agent in ["weather", "flights", "hotels", "activities", "budget"]:
        plan.mark_complete(agent)

    assert plan.is_ready_for_output() is True

def test_error_tracking():
    plan = TravelPlan(
        request=TravelRequest(
            destination="Tokyo",
            origin="Toronto",
            departure_date=date(2025, 8, 1),
            return_date=date(2025, 8, 10),
            budget_usd=4000.0,
        )
    )
    plan.add_error("flight_agent", "API rate limit exceeded")
    assert len(plan.errors) == 1
    assert "flight_agent" in plan.errors[0]