from datetime import date
from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.flight_agent import FlightAgent


def make_plan():
    return TravelPlan(
        request=TravelRequest(
            destination="Tokyo",
            origin="Toronto",
            departure_date=date(2026, 8, 1),
            return_date=date(2026, 8, 10),
            budget_usd=4000.0,
            travelers=1,
        )
    )


def test_flight_agent_fills_plan():
    agent  = FlightAgent()
    plan   = make_plan()
    result = agent.safe_run(plan)

    assert result.flight_options  is not None
    assert len(result.flight_options) > 0
    assert result.selected_flight is not None
    assert "flights" in result.completed_agents


def test_selected_flight_is_cheapest_affordable():
    agent  = FlightAgent()
    plan   = make_plan()
    result = agent.safe_run(plan)

    # selected flight should be within 40% of budget
    flight_budget = plan.request.budget_usd * 0.40
    affordable    = [f for f in result.flight_options
                     if f.price_usd <= flight_budget]

    if affordable:
        assert result.selected_flight.price_usd <= flight_budget

    # selected flight must be the cheapest among its eligible set
    candidates = affordable if affordable else result.flight_options
    assert result.selected_flight.price_usd == min(f.price_usd for f in candidates)


def test_flight_has_required_fields():
    agent  = FlightAgent()
    plan   = make_plan()
    result = agent.safe_run(plan)

    f = result.selected_flight
    assert f.airline        != ""
    assert f.departure_time != ""
    assert f.arrival_time   != ""
    assert f.duration_hours  > 0
    assert f.price_usd       > 0


def test_unknown_city_adds_error():
    agent = FlightAgent()
    plan  = TravelPlan(
        request=TravelRequest(
            destination="Atlantis",
            origin="Toronto",
            departure_date=date(2026, 8, 1),
            return_date=date(2026, 8, 10),
            budget_usd=4000.0,
        )
    )
    result = agent.safe_run(plan)

    assert result.selected_flight is None
    assert len(result.errors) > 0