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


def test_selected_respects_the_target_before_the_cap():
    """
    The selector aims at HOTEL_BUDGET_TARGET, not the cap. The old rule
    maximised stars under the 35% cap, which meant always spending as close
    to the ceiling as allowed — replaced deliberately, so this asserts the
    target is what binds when something fits under it.
    """
    plan = make_plan()
    result = HotelAgent().safe_run(plan)
    target = plan.request.budget_usd * HotelAgent.HOTEL_BUDGET_TARGET

    within_target = [
        h for h in result.hotel_options if h.total_price_usd <= target
    ]
    assert within_target, "fixture should have options under the target"

    best_stars = max(h.stars or 0 for h in within_target)
    assert (result.selected_hotel.stars or 0) == best_stars
    assert result.selected_hotel.total_price_usd <= target


def test_selected_is_cheapest_when_nothing_is_affordable():
    """
    The bug this replaced: with no affordable option, the old selector fell
    through to the whole list and picked the highest-starred property on it,
    handing the tightest budget the Luxury Hotel. Over budget is sometimes
    unavoidable; the honest answer is the cheapest bed.
    """
    plan = make_plan()
    plan.request.budget_usd = 50.0   # nothing will fit at any tier
    result = HotelAgent().safe_run(plan)

    cheapest = min(h.total_price_usd for h in result.hotel_options)
    assert result.selected_hotel.total_price_usd == cheapest


def test_selected_never_exceeds_the_cap_when_something_fits():
    plan = make_plan()
    result = HotelAgent().safe_run(plan)
    cap = plan.request.budget_usd * HotelAgent.HOTEL_BUDGET_CAP

    affordable = [h for h in result.hotel_options if h.total_price_usd <= cap]
    if affordable:
        assert result.selected_hotel.total_price_usd <= cap


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