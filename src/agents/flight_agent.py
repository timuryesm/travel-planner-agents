from __future__ import annotations
import httpx
import random
from datetime import date, timedelta
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, FlightOption
from src.tools.iata_codes import city_to_iata
from src.config.settings import settings


class FlightAgent(BaseAgent):

    name = "flights"
    RAPIDAPI_HOST = "skyscanner50.p.rapidapi.com"

    def run(self, plan: TravelPlan) -> TravelPlan:
        request = plan.request

        # ── 1. Resolve IATA codes ────────────────────────────────────────
        try:
            origin_code = city_to_iata(request.origin)
            dest_code   = city_to_iata(request.destination)
        except ValueError as e:
            plan.add_error(self.name, str(e))
            return plan

        self.logger.info(f"{request.origin} ({origin_code}) → {request.destination} ({dest_code})")

        # ── 2. Fetch flights ─────────────────────────────────────────────
        if settings.RAPIDAPI_KEY:
            try:
                options = self._search_skyscanner(
                    origin_code, dest_code,
                    request.departure_date, request.return_date,
                    request.travelers,
                )
                self.logger.info(f"Skyscanner returned {len(options)} options")
            except Exception as e:
                self.logger.warning(f"Skyscanner API failed ({e}) — using mock data")
                options = self._mock_flights(request.origin, request.destination,
                                             request.departure_date, request.budget_usd)
        else:
            self.logger.info("No RapidAPI key — using mock flight data")
            options = self._mock_flights(request.origin, request.destination,
                                         request.departure_date, request.budget_usd)

        # ── 3. Write back to shared state ────────────────────────────────
        plan.flight_options  = options
        plan.selected_flight = self._select_best(options, request.budget_usd)
        plan.mark_complete(self.name)
        return plan

    # ── Skyscanner via RapidAPI ──────────────────────────────────────────

    def _search_skyscanner(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: date,
        adults: int,
    ) -> list[FlightOption]:

        url = f"https://{self.RAPIDAPI_HOST}/api/v1/searchFlights"
        headers = {
            "X-RapidAPI-Key":  settings.RAPIDAPI_KEY,
            "X-RapidAPI-Host": self.RAPIDAPI_HOST,
        }
        params = {
            "origin":      origin,
            "destination": destination,
            "date":        depart_date.isoformat(),
            "returnDate":  return_date.isoformat(),
            "adults":      adults,
            "currency":    "USD",
            "countryCode": "US",
            "market":      "US",
            "locale":      "en-US",
        }

        response = httpx.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        return self._parse_skyscanner(response.json())

    def _parse_skyscanner(self, raw: dict) -> list[FlightOption]:
        options: list[FlightOption] = []

        # Skyscanner nests results under data → itineraries
        itineraries = (
            raw.get("data", {})
               .get("itineraries", [])
        )

        for it in itineraries[:10]:   # cap at 10 results
            try:
                price = float(
                    it.get("price", {})
                      .get("raw", 0)
                )
                legs = it.get("legs", [])
                if not legs:
                    continue

                leg         = legs[0]
                airline     = (leg.get("carriers", {})
                                  .get("marketing", [{}])[0]
                                  .get("name", "Unknown airline"))
                depart_time = leg.get("departure", "")[:16]   # trim seconds
                arrive_time = leg.get("arrival", "")[:16]
                duration_m  = leg.get("durationInMinutes", 0)

                options.append(FlightOption(
                    airline=airline,
                    departure_time=depart_time,
                    arrival_time=arrive_time,
                    duration_hours=round(duration_m / 60, 1),
                    price_usd=price,
                    booking_url=f"https://www.skyscanner.com/transport/flights/{depart_time[:10]}",
                ))
            except Exception as e:
                self.logger.warning(f"Skipping malformed itinerary: {e}")
                continue

        return options

    # ── Realistic mock fallback ──────────────────────────────────────────

    def _mock_flights(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        budget: float,
    ) -> list[FlightOption]:
        """
        Generates realistic flight options based on route distance.
        Used when no API key is present or the API call fails.
        """
        # Rough base prices by route type
        long_haul  = {"toronto-tokyo", "toronto-london", "toronto-paris",
                      "toronto-dubai", "toronto-singapore", "toronto-bangkok"}
        medium_haul = {"toronto-new york", "toronto-miami", "toronto-los angeles"}

        route = f"{origin.lower()}-{destination.lower()}"
        if route in long_haul:
            base_price, duration = 850, 14.5
        elif route in medium_haul:
            base_price, duration = 280, 2.5
        else:
            base_price, duration = 600, 10.0

        airlines = ["Air Canada", "Japan Airlines", "ANA", "United Airlines",
                    "British Airways", "Cathay Pacific", "Korean Air"]

        options = []
        for i in range(5):
            # Vary price ±20% and duration ±1.5h for each option
            price    = round(base_price * random.uniform(0.85, 1.20), 2)
            dur      = round(duration + random.uniform(-1.5, 1.5), 1)
            dep_hour = 8 + (i * 3)                               # spread across the day
            dep_time = f"{depart_date}T{dep_hour:02d}:00"
            arr_time = f"{depart_date}T{(dep_hour + int(dur)) % 24:02d}:30"

            options.append(FlightOption(
                airline=airlines[i % len(airlines)],
                departure_time=dep_time,
                arrival_time=arr_time,
                duration_hours=dur,
                price_usd=price,
                booking_url=f"https://www.skyscanner.com/transport/flights/{depart_date}",
            ))

        return options

    # ── Selection logic ──────────────────────────────────────────────────

    def _select_best(
        self,
        options: list[FlightOption],
        budget_usd: float,
    ) -> FlightOption | None:
        if not options:
            return None

        # Prefer cheapest flight under 40% of total budget
        flight_budget = budget_usd * 0.40
        affordable    = [f for f in options if f.price_usd <= flight_budget]
        candidates    = affordable if affordable else options

        # Among candidates, pick lowest price
        return min(candidates, key=lambda f: f.price_usd)