from datetime import date
from src.state.travel_plan import (
    TravelPlan, TravelRequest, FlightOption, FlightLeg,
    HotelOption, Activity,
)
from src.agents.budget_agent import BudgetAgent


def make_full_plan():
    plan = TravelPlan(
        request=TravelRequest(
            destination="Tokyo", origin="Toronto",
            departure_date=date(2026, 8, 1), return_date=date(2026, 8, 10),
            budget_usd=4000.0, travelers=1,
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
        name="Test Hotel", location="Tokyo",
        price_per_night_usd=100.0, total_price_usd=900.0,
    )
    plan.activities = [
        Activity(name="Temple", description="Visit", estimated_cost_usd=20.0,
                 duration_hours=2.0, category="culture"),
        Activity(name="Food tour", description="Eat", estimated_cost_usd=80.0,
                 duration_hours=3.0, category="food"),
    ]
    return plan


def test_budget_sums_all_components():
    result = BudgetAgent().safe_run(make_full_plan())
    b = result.budget
    assert b.flights_usd    == 1400.0
    assert b.hotel_usd      == 900.0
    assert b.activities_usd == 100.0       # 20 + 80
    assert b.miscellaneous_usd == 360.0    # 40 * 9 nights * 1 traveler
    assert b.total_usd      == 2760.0      # 1400 + 900 + 100 + 360


def test_within_budget_flag_true():
    result = BudgetAgent().safe_run(make_full_plan())  # 2760 < 4000
    assert result.budget.within_budget is True


def test_over_budget_flag():
    plan = make_full_plan()
    plan.request.budget_usd = 2000.0      # less than 2760 total
    result = BudgetAgent().safe_run(plan)
    assert result.budget.within_budget is False


def test_budget_handles_missing_components():
    plan = TravelPlan(
        request=TravelRequest(
            destination="Tokyo", origin="Toronto",
            departure_date=date(2026, 8, 1), return_date=date(2026, 8, 10),
            budget_usd=4000.0, travelers=1,
        )
    )
    result = BudgetAgent().safe_run(plan)   # nothing selected
    assert result.budget.flights_usd    == 0.0
    assert result.budget.hotel_usd      == 0.0
    assert result.budget.activities_usd == 0.0
    assert "budget" in result.completed_agents


def test_misc_scales_with_travelers():
    plan = make_full_plan()
    plan.request.travelers = 2
    result = BudgetAgent().safe_run(plan)
    assert result.budget.miscellaneous_usd == 720.0   # 40 * 9 * 2