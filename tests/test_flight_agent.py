from datetime import date
from src.state.travel_plan import TravelPlan, TravelRequest, FlightOption, FlightLeg
from src.agents.flight_agent import FlightAgent


def make_plan(trip_type="roundtrip"):
    return TravelPlan(
        request=TravelRequest(
            destination="Tokyo",
            origin="Toronto",
            departure_date=date(2026, 8, 1),
            return_date=date(2026, 8, 10),
            budget_usd=4000.0,
            travelers=1,
            trip_type=trip_type,
        )
    )


def test_flight_agent_fills_plan():
    result = FlightAgent().safe_run(make_plan())
    assert result.flight_options is not None
    assert len(result.flight_options) > 0
    assert result.selected_flight is not None
    assert "flights" in result.completed_agents


def test_roundtrip_has_two_legs():
    result = FlightAgent().safe_run(make_plan("roundtrip"))
    f = result.selected_flight
    assert f.trip_type == "roundtrip"
    assert len(f.legs) == 2
    assert f.legs[0].origin == "Toronto"
    assert f.legs[1].origin == "Tokyo"


def test_one_way_has_one_leg():
    result = FlightAgent().safe_run(make_plan("one_way"))
    f = result.selected_flight
    assert f.trip_type == "one_way"
    assert len(f.legs) == 1


def test_booking_url_format():
    result = FlightAgent().safe_run(make_plan("roundtrip"))
    url = result.selected_flight.booking_url
    assert "skyscanner.com" in url
    assert "ytoa" in url      # Toronto city code (YTO) + 'a'
    assert "tyoa" in url      # Tokyo city code (TYO) + 'a'
    assert "260801" in url    # Aug 1 2026
    assert "260810" in url    # Aug 10 2026


def test_selected_is_cheapest_affordable():
    result = FlightAgent().safe_run(make_plan())
    budget = result.request.budget_usd * 0.40
    affordable = [f for f in result.flight_options if f.price_usd <= budget]
    candidates = affordable if affordable else result.flight_options
    assert result.selected_flight.price_usd == min(f.price_usd for f in candidates)


def test_unknown_city_still_gets_options():
    """
    A city outside the IATA table must NOT kill the stage.

    This used to assert the opposite: lookup_iata raised, the agent returned
    early with flight_options still None, and the adapter served an empty
    list — a flights stage offering nothing but "I've booked my own", with
    nothing logged because nothing was raised. The IATA code is used only in
    a log line, so it now degrades to the city name.
    """
    plan = TravelPlan(
        request=TravelRequest(
            destination="Atlantis", origin="Toronto",
            departure_date=date(2026, 8, 1), return_date=date(2026, 8, 10),
            budget_usd=4000.0,
        )
    )
    result = FlightAgent().safe_run(plan)

    assert result.flight_options, "an unknown city should still get mock flights"
    assert result.selected_flight is not None
    assert not result.errors
    # No Skyscanner city code for Atlantis, so the deep link would be built
    # from a guessed code pointing at the wrong route — degrades to the
    # homepage instead.
    assert result.selected_flight.booking_url == "https://www.skyscanner.com/"