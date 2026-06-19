from datetime import date
from unittest.mock import patch, MagicMock
from src.state.travel_plan import (
    TravelPlan, TravelRequest, FlightOption, FlightLeg,
    HotelOption, Activity, WeatherSummary, BudgetBreakdown,
)
from src.agents.orchestrator import Orchestrator


def make_full_plan():
    plan = TravelPlan(
        request=TravelRequest(
            destination="Tokyo", origin="Toronto",
            departure_date=date(2026, 8, 1), return_date=date(2026, 8, 4),
            budget_usd=4000.0, travelers=1, interests=["food"],
        )
    )
    plan.selected_flight = FlightOption(
        trip_type="roundtrip",
        legs=[FlightLeg(airline="ANA", origin="Toronto", destination="Tokyo",
                        departure_time="2026-08-01T17:00", arrival_time="2026-08-02T20:00",
                        duration_hours=14.0)],
        price_usd=1400.0,
    )
    plan.selected_hotel = HotelOption(
        name="Test Hotel", location="Shinjuku, Tokyo",
        price_per_night_usd=100.0, total_price_usd=300.0, stars=4.0,
    )
    plan.weather = WeatherSummary(
        location="Tokyo",
        forecast_by_day={"2026-08-01": "Sunny, 30C", "2026-08-02": "Rain, 26C"},
        packing_tips=["Bring an umbrella"],
    )
    plan.activities = [
        Activity(name="Sushi tour", description="Eat sushi",
                 estimated_cost_usd=50.0, duration_hours=2.0, category="food"),
    ]
    plan.budget = BudgetBreakdown(
        flights_usd=1400.0, hotel_usd=300.0, activities_usd=50.0,
        miscellaneous_usd=120.0, total_usd=1870.0, within_budget=True,
    )
    for agent in ["weather", "flights", "hotels", "activities", "budget"]:
        plan.mark_complete(agent)
    return plan


def test_build_context_includes_all_sections():
    orchestrator = Orchestrator()
    plan = make_full_plan()
    context = orchestrator._build_context(plan)

    assert "FLIGHT" in context
    assert "ACCOMMODATION" in context
    assert "WEATHER" in context
    assert "ACTIVITIES" in context
    assert "BUDGET" in context
    assert "ANA" in context          # flight airline
    assert "Test Hotel" in context   # hotel name
    assert "Sushi tour" in context   # activity


def test_assemble_itinerary_sets_markdown():
    orchestrator = Orchestrator()
    plan = make_full_plan()

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="# Your Tokyo Trip\n\nDay 1...")]

    with patch.object(orchestrator.client.messages, "create", return_value=mock_response):
        result = orchestrator.assemble_itinerary(plan)

    assert result.startswith("# Your Tokyo Trip")
    assert plan.itinerary_markdown == result