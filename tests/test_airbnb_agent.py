from datetime import date
from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.airbnb_agent import AirbnbAgent
from src.agents.hotel_agent import HotelAgent


def make_plan(providers=None):
    return TravelPlan(
        request=TravelRequest(
            destination="Tokyo",
            origin="Toronto",
            departure_date=date(2026, 8, 1),
            return_date=date(2026, 8, 10),
            budget_usd=4000.0,
            travelers=1,
            accommodation_providers=providers or ["airbnb"],
        )
    )


def test_airbnb_agent_fills_plan():
    result = AirbnbAgent().safe_run(make_plan())
    assert result.hotel_options  is not None
    assert len(result.hotel_options) > 0
    assert result.selected_hotel is not None
    assert "airbnb" in result.completed_agents


def test_airbnb_listings_have_provider_tag():
    result = AirbnbAgent().safe_run(make_plan())
    for listing in result.hotel_options:
        assert listing.provider == "airbnb"


def test_airbnb_and_booking_combine_results():
    """Both agents running should produce combined hotel_options."""
    plan = make_plan(providers=["booking.com", "airbnb"])
    plan = HotelAgent().safe_run(plan)
    plan = AirbnbAgent().safe_run(plan)

    providers = {h.provider for h in plan.hotel_options}
    assert "booking.com" in providers
    assert "airbnb" in providers


def test_selected_hotel_is_best_across_providers():
    """Selected hotel should be the best option across all providers."""
    plan = make_plan(providers=["booking.com", "airbnb"])
    plan = HotelAgent().safe_run(plan)
    plan = AirbnbAgent().safe_run(plan)

    hotel_budget = plan.request.budget_usd * 0.35
    affordable   = [h for h in plan.hotel_options
                    if h.total_price_usd <= hotel_budget]
    if affordable:
        best_stars = max(h.stars or 0 for h in affordable)
        assert (plan.selected_hotel.stars or 0) == best_stars


def test_airbnb_booking_url_format():
    result = AirbnbAgent().safe_run(make_plan())
    for listing in result.hotel_options:
        assert "airbnb.com" in listing.booking_url