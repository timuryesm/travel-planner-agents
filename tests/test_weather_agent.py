from datetime import date
from unittest.mock import patch, MagicMock
from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.weather_agent import WeatherAgent


def make_plan(destination="Tokyo"):
    return TravelPlan(
        request=TravelRequest(
            destination=destination,
            origin="Toronto",
            departure_date=date(2026, 8, 1),   # future date
            return_date=date(2026, 8, 5),
            budget_usd=4000.0,
        )
    )


# Historical archive returns last year's dates (2025) for a 2026 trip
MOCK_OPEN_METEO_RESPONSE = {
    "daily": {
        "time":               ["2025-08-01", "2025-08-02", "2025-08-03"],
        "weather_code":       [0, 61, 3],
        "temperature_2m_max": [33.0, 29.0, 27.0],
        "temperature_2m_min": [26.0, 24.0, 22.0],
    }
}


def test_weather_agent_fills_plan():
    agent = WeatherAgent()
    plan  = make_plan()

    mock_location = MagicMock()
    mock_location.latitude  = 35.6895
    mock_location.longitude = 139.6917

    mock_response = MagicMock()
    mock_response.json.return_value = MOCK_OPEN_METEO_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("src.agents.weather_agent.Nominatim") as mock_geo, \
         patch("src.agents.weather_agent.httpx.get", return_value=mock_response):

        mock_geo.return_value.geocode.return_value = mock_location
        result = agent.safe_run(plan)

    assert result.weather is not None
    assert result.weather.location == "Tokyo"
    assert len(result.weather.forecast_by_day) == 3       # 3 days of data
    assert "weather" in result.completed_agents


def test_weather_forecast_content():
    agent = WeatherAgent()
    plan  = make_plan()

    mock_location = MagicMock()
    mock_location.latitude  = 35.6895
    mock_location.longitude = 139.6917

    mock_response = MagicMock()
    mock_response.json.return_value = MOCK_OPEN_METEO_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("src.agents.weather_agent.Nominatim") as mock_geo, \
         patch("src.agents.weather_agent.httpx.get", return_value=mock_response):

        mock_geo.return_value.geocode.return_value = mock_location
        result = agent.safe_run(plan)

    # Check values exist without depending on specific date keys
    values = list(result.weather.forecast_by_day.values())

    assert any("Clear sky" in v for v in values)    # code 0 = Clear sky
    assert any("Light rain" in v for v in values)   # code 61 = Light rain
    assert any("33" in v for v in values)           # 33°C max

    # Rain on day 2 should trigger umbrella tip
    assert any("umbrella" in tip.lower() or "rain" in tip.lower()
               for tip in result.weather.packing_tips)


def test_weather_agent_handles_geocode_failure():
    agent = WeatherAgent()
    plan  = make_plan(destination="ThisCityDoesNotExist")

    with patch("src.agents.weather_agent.Nominatim") as mock_geo:
        mock_geo.return_value.geocode.return_value = None
        result = agent.safe_run(plan)

    assert result.weather is None
    assert "weather" not in result.completed_agents
    assert len(result.errors) == 1