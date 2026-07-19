"""
Tests for BudgetAgent.aggregate() — the pure shared total.

These complement test_budget_agent.py, which covers the run(plan) path. This
file tests aggregate() directly: no TravelPlan, no DB, no mocks — the whole
point of reducing both callers to numbers is that the calculation tests like
arithmetic.
"""
from src.agents.budget_agent import BudgetAgent


def test_aggregate_totals_and_misc():
    b = BudgetAgent.aggregate(
        flights_usd=1200, hotel_usd=900, activities_usd=300,
        budget_usd=3000, nights=6, travelers=2,
    )
    assert b.miscellaneous_usd == 480.0          # 40 * 6 * 2
    assert b.total_usd == 2880.0                 # 1200 + 900 + 300 + 480
    assert b.within_budget is True
    assert b.intercity_usd == 0.0


def test_aggregate_over_budget_and_missing_note():
    b = BudgetAgent.aggregate(
        flights_usd=0, hotel_usd=5000, activities_usd=0,
        budget_usd=3000, nights=3, travelers=1, missing=["flights"],
    )
    assert b.within_budget is False
    assert any("over budget" in n for n in b.notes)
    assert any("No flight selected" in n for n in b.notes)


def test_misc_scales_with_nights_not_trip_window():
    # The reason nights is a parameter: a hotel stay shorter than the trip
    # (nights spent in spokes) costs less misc. 2 nights, not the trip length.
    b = BudgetAgent.aggregate(
        flights_usd=0, hotel_usd=0, activities_usd=0,
        budget_usd=1000, nights=2, travelers=1,
    )
    assert b.miscellaneous_usd == 80.0           # 40 * 2 * 1


def test_intercity_is_included_in_total():
    b = BudgetAgent.aggregate(
        flights_usd=500, hotel_usd=500, activities_usd=0, intercity_usd=200,
        budget_usd=2000, nights=0, travelers=1,
    )
    assert b.intercity_usd == 200.0
    assert b.total_usd == 1200.0                 # 500 + 500 + 0 + 200 + 0 misc


def test_zero_nights_no_negative_misc():
    # nights can be 0 (e.g. a same-day check-in/out edge); misc must not go negative.
    b = BudgetAgent.aggregate(
        flights_usd=0, hotel_usd=0, activities_usd=0,
        budget_usd=100, nights=0, travelers=3,
    )
    assert b.miscellaneous_usd == 0.0