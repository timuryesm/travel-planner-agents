from __future__ import annotations
import httpx
import random
from datetime import date, datetime, timedelta
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, FlightOption, FlightLeg
from src.tools.airport_lookup import lookup_iata, city_to_skyscanner_code
from src.config.settings import settings


class FlightAgent(BaseAgent):

    name = "flights"
    RAPIDAPI_HOST = "skyscanner-flights-travel-api.p.rapidapi.com"

    def run(self, plan: TravelPlan) -> TravelPlan:
        req = plan.request

        # ── 1. Resolve IATA codes ────────────────────────────────────────
        try:
            origin_iata = lookup_iata(req.origin, settings.RAPIDAPI_KEY)
            dest_iata   = lookup_iata(req.destination, settings.RAPIDAPI_KEY)
        except ValueError as e:
            plan.add_error(self.name, str(e))
            return plan

        self.logger.info(
            f"{req.origin} ({origin_iata}) → {req.destination} ({dest_iata}) "
            f"[{req.trip_type}]"
        )

        # ── 2. Fetch flights ─────────────────────────────────────────────
        if settings.RAPIDAPI_KEY:
            try:
                options = self._search_skyscanner(
                    origin_iata, dest_iata,
                    req.origin, req.destination,
                    req.departure_date, req.return_date,
                    req.travelers, req.trip_type,
                )
                self.logger.info(f"Skyscanner returned {len(options)} options")
            except Exception as e:
                self.logger.warning(f"Skyscanner failed ({e}) — using mock data")
                options = self._mock_flights(
                    req.origin, req.destination,
                    req.departure_date, req.return_date,
                    req.trip_type, req.budget_usd, req.travelers,
                )
        else:
            self.logger.info("No RapidAPI key — using mock flight data")
            options = self._mock_flights(
                req.origin, req.destination,
                req.departure_date, req.return_date,
                req.trip_type, req.budget_usd, req.travelers,
            )

        # ── 3. Write back ────────────────────────────────────────────────
        plan.flight_options  = options
        plan.selected_flight = self._select_best(options, req.budget_usd)
        plan.mark_complete(self.name)
        return plan

    # ── Skyscanner API ───────────────────────────────────────────────────

    def _search_skyscanner(
        self,
        origin_iata: str,
        dest_iata: str,
        origin_city: str,
        dest_city: str,
        depart_date: date,
        return_date: date,
        adults: int,
        trip_type: str,
    ) -> list[FlightOption]:
        params = {
            "origin":      origin_iata,
            "destination": dest_iata,
            "date":        depart_date.isoformat(),
            "adults":      adults,
            "currency":    "USD",
            "countryCode": "US",
            "market":      "US",
            "locale":      "en-US",
        }
        if trip_type == "roundtrip":
            params["returnDate"] = return_date.isoformat()

        response = httpx.get(
            f"https://{self.RAPIDAPI_HOST}/api/v1/searchFlights",
            headers={
                "X-RapidAPI-Key":  settings.RAPIDAPI_KEY,
                "X-RapidAPI-Host": self.RAPIDAPI_HOST,
            },
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        return self._parse_skyscanner(
            response.json(),
            origin_city, dest_city,
            depart_date, return_date,
            adults, trip_type,
        )

    def _parse_skyscanner(
        self,
        raw: dict,
        origin_city: str,
        dest_city: str,
        depart_date: date,
        return_date: date,
        adults: int,
        trip_type: str,
    ) -> list[FlightOption]:
        options: list[FlightOption] = []
        for it in raw.get("data", {}).get("itineraries", [])[:10]:
            try:
                price = float(it.get("price", {}).get("raw", 0))
                legs: list[FlightLeg] = []
                for leg in it.get("legs", []):
                    airline = (
                        leg.get("carriers", {})
                           .get("marketing", [{}])[0]
                           .get("name", "Unknown")
                    )
                    legs.append(FlightLeg(
                        airline=airline,
                        origin=origin_city,
                        destination=dest_city,
                        departure_time=leg.get("departure", "")[:16],
                        arrival_time=leg.get("arrival", "")[:16],
                        duration_hours=round(
                            leg.get("durationInMinutes", 0) / 60, 1
                        ),
                    ))
                options.append(FlightOption(
                    trip_type=trip_type,
                    legs=legs,
                    price_usd=price,
                    booking_url=self._build_booking_url(
                        origin_city, dest_city,
                        depart_date, return_date,
                        trip_type, adults,
                    ),
                ))
            except Exception as e:
                self.logger.warning(f"Skipping itinerary: {e}")
        return options

    # ── Booking URL ──────────────────────────────────────────────────────

    def _build_booking_url(
        self,
        origin_city: str,
        dest_city: str,
        depart_date: date,
        return_date: date,
        trip_type: str,
        adults: int,
    ) -> str:
        """
        Build a working Skyscanner search URL.
        Uses city-level codes (YTO, TYO) not airport codes (YYZ, NRT).
        Format: skyscanner.com/transport/flights/{city}a/{city}a/YYMMDD/YYMMDD/
        """
        orig = city_to_skyscanner_code(origin_city).lower() + "a"
        dest = city_to_skyscanner_code(dest_city).lower() + "a"
        dep  = depart_date.strftime("%y%m%d")

        if trip_type == "one_way":
            return (
                f"https://www.skyscanner.com/transport/flights/"
                f"{orig}/{dest}/{dep}/"
                f"?adultsv2={adults}&cabinclass=economy&rtn=0"
            )
        elif trip_type == "roundtrip":
            ret = return_date.strftime("%y%m%d")
            return (
                f"https://www.skyscanner.com/transport/flights/"
                f"{orig}/{dest}/{dep}/{ret}/"
                f"?adultsv2={adults}&cabinclass=economy&rtn=1"
            )
        else:
            return "https://www.skyscanner.com/flights-multi-city.aspx"

    # ── Mock data ────────────────────────────────────────────────────────

    def _mock_flights(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: date,
        trip_type: str,
        budget: float,
        travelers: int,
    ) -> list[FlightOption]:
        """Generate realistic mock flight options with correct date arithmetic."""
        base_price, base_dur = self._estimate_route(origin, destination)
        airlines = [
            "Air Canada", "Japan Airlines", "ANA",
            "United Airlines", "British Airways",
            "Cathay Pacific", "Korean Air",
        ]
        options = []

        for i in range(5):
            mult    = random.uniform(0.85, 1.20)
            dur     = round(base_dur + random.uniform(-1.5, 1.5), 1)
            dep_h   = 8 + (i * 3)
            airline = airlines[i % len(airlines)]

            # Use datetime arithmetic so arrival rolls over to the next day correctly
            dep_dt  = datetime(depart_date.year, depart_date.month, depart_date.day, dep_h, 0)
            arr_dt  = dep_dt + timedelta(hours=dur)

            outbound = FlightLeg(
                airline=airline,
                origin=origin,
                destination=destination,
                departure_time=dep_dt.strftime("%Y-%m-%dT%H:%M"),  # string, not datetime
                arrival_time=arr_dt.strftime("%Y-%m-%dT%H:%M"),    # string, not datetime
                duration_hours=dur,
            )

            if trip_type == "one_way":
                legs  = [outbound]
                price = round(base_price * mult * travelers, 2)

            elif trip_type == "roundtrip":
                ret_h   = 9 + (i * 2)
                ret_dep = datetime(return_date.year, return_date.month, return_date.day, ret_h, 0)
                ret_arr = ret_dep + timedelta(hours=dur)
                legs = [
                    outbound,
                    FlightLeg(
                        airline=airline,
                        origin=destination,
                        destination=origin,
                        departure_time=ret_dep.strftime("%Y-%m-%dT%H:%M"),  # string
                        arrival_time=ret_arr.strftime("%Y-%m-%dT%H:%M"),    # string
                        duration_hours=dur,
                    ),
                ]
                price = round(base_price * 1.85 * mult * travelers, 2)

            else:  # multi_city
                legs  = [outbound]
                price = round(base_price * 1.5 * mult * travelers, 2)

            options.append(FlightOption(
                trip_type=trip_type,
                legs=legs,
                price_usd=price,
                booking_url=self._build_booking_url(
                    origin, destination,
                    depart_date, return_date,
                    trip_type, travelers,
                ),
            ))

        return options

    # ── Helpers ──────────────────────────────────────────────────────────

    def _estimate_route(self, origin: str, dest: str) -> tuple[float, float]:
        """Return (base_price_usd, base_duration_hours) for a route."""
        long_haul = {
            "toronto-tokyo", "toronto-osaka", "toronto-seoul",
            "toronto-beijing", "toronto-shanghai", "toronto-singapore",
            "toronto-bangkok", "toronto-dubai", "toronto-sydney",
            "toronto-london", "toronto-paris", "toronto-amsterdam",
            "toronto-frankfurt", "toronto-rome", "toronto-madrid",
        }
        medium_haul = {
            "toronto-new york", "toronto-miami", "toronto-chicago",
            "toronto-los angeles", "toronto-san francisco",
            "toronto-denver", "toronto-cancun", "toronto-mexico city",
        }
        route = f"{origin.lower()}-{dest.lower()}"
        rev   = f"{dest.lower()}-{origin.lower()}"
        if route in long_haul or rev in long_haul:
            return 850.0, 14.5
        if route in medium_haul or rev in medium_haul:
            return 280.0, 2.5
        return 550.0, 9.0

    def _select_best(
        self, options: list[FlightOption], budget_usd: float
    ) -> FlightOption | None:
        if not options:
            return None
        flight_budget = budget_usd * 0.40
        affordable    = [f for f in options if f.price_usd <= flight_budget]
        candidates    = affordable if affordable else options
        return min(candidates, key=lambda f: f.price_usd)