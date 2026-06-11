from __future__ import annotations
import httpx
from datetime import date, timedelta
from geopy.geocoders import Nominatim
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, WeatherSummary


# WMO weather code → human readable description
# https://open-meteo.com/en/docs#weathervariables
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

    def run(self, plan: TravelPlan) -> TravelPlan:
        destination = plan.request.destination
        departure   = plan.request.departure_date
        return_date = plan.request.return_date

        # ── 1. Geocode city name → lat/lon ───────────────────────────────
        self.logger.info(f"Geocoding '{destination}'")
        lat, lon = self._geocode(destination)
        self.logger.info(f"Coordinates: {lat:.3f}, {lon:.3f}")

        # ── 2. Fetch forecast from Open-Meteo ────────────────────────────
        self.logger.info(f"Fetching forecast {departure} → {return_date}")
        raw = self._fetch_forecast(lat, lon, departure, return_date)

        # ── 3. Parse into WeatherSummary ─────────────────────────────────
        summary = self._parse(destination, raw)

        # ── 4. Write back to shared state ────────────────────────────────
        plan.weather = summary
        plan.mark_complete(self.name)
        return plan

    # ── Private helpers ──────────────────────────────────────────────────

    def _geocode(self, city: str) -> tuple[float, float]:
        geolocator = Nominatim(user_agent="travel-planner-agents")
        location = geolocator.geocode(city)
        if not location:
            raise ValueError(f"Could not geocode city: '{city}'")
        return location.latitude, location.longitude

    def _fetch_forecast(
        self,
        lat: float,
        lon: float,
        start: date,
        end: date,
    ) -> dict:
        # Open-Meteo supports up to 16 days ahead for free
        params = {
            "latitude":        lat,
            "longitude":       lon,
            "daily":           "weathercode,temperature_2m_max,temperature_2m_min",
            "temperature_unit": "celsius",
            "start_date":      start.isoformat(),
            "end_date":        end.isoformat(),
            "timezone":        "auto",
        }
        response = httpx.get(self.BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def _parse(self, destination: str, raw: dict) -> WeatherSummary:
        daily = raw.get("daily", {})
        dates      = daily.get("time", [])
        codes      = daily.get("weathercode", [])
        temps_max  = daily.get("temperature_2m_max", [])
        temps_min  = daily.get("temperature_2m_min", [])

        forecast_by_day: dict[str, str] = {}
        for d, code, t_max, t_min in zip(dates, codes, temps_max, temps_min):
            description = WMO_CODES.get(int(code), "Unknown")
            forecast_by_day[d] = f"{description}, {t_min:.0f}–{t_max:.0f}°C"

        packing_tips = self._packing_tips(codes, temps_max)

        return WeatherSummary(
            location=destination,
            forecast_by_day=forecast_by_day,
            packing_tips=packing_tips,
        )

    def _packing_tips(
        self,
        codes: list[int],
        temps_max: list[float],
    ) -> list[str]:
        tips: list[str] = []
        avg_temp = sum(temps_max) / len(temps_max) if temps_max else 20

        if avg_temp > 28:
            tips.append("Pack light, breathable clothing — it will be hot")
        elif avg_temp < 10:
            tips.append("Bring a warm coat and layers")
        else:
            tips.append("Mild temperatures — a light jacket should suffice")

        rain_codes = {51,53,55,61,63,65,80,81,82,95,96}
        rainy_days = sum(1 for c in codes if int(c) in rain_codes)
        if rainy_days >= 3:
            tips.append(f"Rain expected on {rainy_days} days — pack an umbrella")
        elif rainy_days >= 1:
            tips.append("Some rain possible — a small umbrella is useful")

        snow_codes = {71,73,75}
        if any(int(c) in snow_codes for c in codes):
            tips.append("Snow possible — waterproof boots recommended")

        return tips or ["No special weather gear needed"]