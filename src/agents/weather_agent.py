from __future__ import annotations
import httpx
from datetime import date, timedelta
from geopy.geocoders import Nominatim
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, WeatherSummary

WMO_CODES: dict[int, str] = {
    0:  "Clear sky",
    1:  "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy",        48: "Icy fog",
    51: "Light drizzle",53: "Drizzle",      55: "Heavy drizzle",
    61: "Light rain",   63: "Rain",         65: "Heavy rain",
    71: "Light snow",   73: "Snow",         75: "Heavy snow",
    80: "Rain showers", 81: "Showers",      82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail",
}


class WeatherAgent(BaseAgent):

    name = "weather"
    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"


    def run(self, plan: TravelPlan) -> TravelPlan:
        destination = plan.request.destination
        departure   = plan.request.departure_date
        return_date = plan.request.return_date

        self.logger.info(f"Geocoding '{destination}'")
        lat, lon = self._geocode(destination)
        self.logger.info(f"Coordinates: {lat:.3f}, {lon:.3f}")

        self.logger.info(f"Fetching forecast {departure} -> {return_date}")
        raw, is_historical = self._fetch_forecast(lat, lon, departure, return_date)

        summary = self._parse(destination, raw, is_historical)

        plan.weather = summary
        plan.mark_complete(self.name)
        return plan

    def _geocode(self, city: str) -> tuple[float, float]:
        geolocator = Nominatim(user_agent="travel-planner-agents")
        location = geolocator.geocode(city)
        if not location:
            raise ValueError(f"Could not geocode city: '{city}'")
        return location.latitude, location.longitude


    def _fetch_forecast(self, lat: float, lon: float, start: date, end: date) -> tuple[dict, bool]:
        today = date.today()
        max_forecast_date = today + timedelta(days=15)

        if today <= start <= max_forecast_date:
            # Near future — use real forecast
            self.logger.info("Using live forecast (within 15 days)")
            params = {
                "latitude":         lat,
                "longitude":        lon,
                "daily":            "weather_code,temperature_2m_max,temperature_2m_min",
                "temperature_unit": "celsius",
                "start_date":       start.isoformat(),
                "end_date":         end.isoformat(),
                "timezone":         "auto",
            }
            response = httpx.get(self.FORECAST_URL, params=params, timeout=10)
            response.raise_for_status()
            return response.json(), False

        else:
            # Past date OR far future — use same calendar dates from last year
            historical_start = start.replace(year=start.year - 1)
            historical_end   = end.replace(year=end.year - 1)

            if start < today:
                self.logger.info(f"Past date — using {historical_start} as historical proxy")
            else:
                self.logger.info(f"Far future — using {historical_start} as seasonal proxy")

            params = {
                "latitude":         lat,
                "longitude":        lon,
                "daily":            "weather_code,temperature_2m_max,temperature_2m_min",
                "temperature_unit": "celsius",
                "start_date":       historical_start.isoformat(),
                "end_date":         historical_end.isoformat(),
                "timezone":         "auto",
            }
            response = httpx.get(self.ARCHIVE_URL, params=params, timeout=10)
            response.raise_for_status()
            return response.json(), True

    def _parse(self, destination: str, raw: dict, is_historical: bool = False) -> WeatherSummary:
        daily     = raw.get("daily", {})
        dates     = daily.get("time", [])
        codes     = daily.get("weather_code", [])
        temps_max = daily.get("temperature_2m_max", [])
        temps_min = daily.get("temperature_2m_min", [])

        forecast_by_day: dict[str, str] = {}
        for d, code, t_max, t_min in zip(dates, codes, temps_max, temps_min):
            description = WMO_CODES.get(int(code), "Unknown")
            label = "(typical) " if is_historical else ""
            forecast_by_day[d] = f"{label}{description}, {t_min:.0f}-{t_max:.0f}C"

        packing_tips = self._packing_tips(codes, temps_max)
        if is_historical:
            packing_tips.insert(0, "Forecast based on historical data for this time of year")

        return WeatherSummary(
            location=destination,
            forecast_by_day=forecast_by_day,
            packing_tips=packing_tips,
        )

    def _packing_tips(self, codes: list[int], temps_max: list[float]) -> list[str]:
        tips: list[str] = []
        avg_temp = sum(temps_max) / len(temps_max) if temps_max else 20

        if avg_temp > 28:
            tips.append("Pack light, breathable clothing -- it will be hot")
        elif avg_temp < 10:
            tips.append("Bring a warm coat and layers")
        else:
            tips.append("Mild temperatures -- a light jacket should suffice")

        rain_codes = {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96}
        rainy_days = sum(1 for c in codes if int(c) in rain_codes)
        if rainy_days >= 3:
            tips.append(f"Rain expected on {rainy_days} days -- pack an umbrella")
        elif rainy_days >= 1:
            tips.append("Some rain possible -- a small umbrella is useful")

        snow_codes = {71, 73, 75}
        if any(int(c) in snow_codes for c in codes):
            tips.append("Snow possible -- waterproof boots recommended")

        return tips or ["No special weather gear needed"]