from datetime import date
from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.hotel_agent import HotelAgent


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


def test_hotel_agent_fills_plan():
    result = HotelAgent().safe_run(make_plan())
    assert result.hotel_options  is not None
    assert len(result.hotel_options) > 0
    assert result.selected_hotel is not None
    assert "hotels" in result.completed_agents


def test_selected_hotel_within_budget():
    result = HotelAgent().safe_run(make_plan())
    hotel_budget = make_plan().request.budget_usd * 0.35
    affordable   = [h for h in result.hotel_options
                    if h.total_price_usd <= hotel_budget]
    if affordable:
        assert result.selected_hotel.total_price_usd <= hotel_budget


def test_selected_is_highest_stars_among_affordable():
    result = HotelAgent().safe_run(make_plan())
    hotel_budget = make_plan().request.budget_usd * 0.35
    affordable   = [h for h in result.hotel_options
                    if h.total_price_usd <= hotel_budget]
    if affordable:
        best_stars = max(h.stars or 0 for h in affordable)
        assert (result.selected_hotel.stars or 0) == best_stars


def test_hotel_has_required_fields():
    result = HotelAgent().safe_run(make_plan())
    h = result.selected_hotel
    assert h.name               != ""
    assert h.location           != ""
    assert h.price_per_night_usd > 0
    assert h.total_price_usd     > 0
    assert h.booking_url        is not None
    assert "booking.com"        in h.booking_url


def test_total_price_equals_nightly_times_nights():
    result = HotelAgent().safe_run(make_plan())
    nights = (
        make_plan().request.return_date
        - make_plan().request.departure_date
    ).days
    for h in result.hotel_options:
        expected = round(h.price_per_night_usd * nights, 2)
        assert abs(h.total_price_usd - expected) < 0.10  # allow rounding