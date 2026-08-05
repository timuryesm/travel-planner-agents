from __future__ import annotations
import httpx
import random
import time
from datetime import date, datetime, timedelta
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, FlightOption, FlightLeg
from src.tools.airport_lookup import (
    lookup_iata,
    lookup_skyscanner_ids,
    city_to_skyscanner_code,
    has_skyscanner_code,
)
from src.config.settings import settings


class FlightAgent(BaseAgent):

    name = "flights"
    RAPIDAPI_HOST = "skyscanner-flights-travel-api.p.rapidapi.com"

    def run(self, plan: TravelPlan) -> TravelPlan:
        req = plan.request

       # IATA codes are for the log line only — the mock path builds legs from
        # city names, the booking URL uses city_to_skyscanner_code, and the
        # real search uses lookup_skyscanner_ids. So a city missing from the
        # fallback table must NOT stop the stage.
        #
        # It used to: an unresolved code returned early with flight_options
        # still None, the adapter read that as an empty list, and the user got
        # a flights stage offering nothing but "I've booked my own" — with no
        # warning in the log, because nothing was raised. Punta Cana found it.
        def _iata_or_city(city: str) -> str:
            try:
                return lookup_iata(city)
            except ValueError:
                self.logger.info(f"No IATA code for '{city}' — using the name")
                return city

        origin_iata = _iata_or_city(req.origin)
        dest_iata = _iata_or_city(req.destination)

        self.logger.info(
            f"{req.origin} ({origin_iata}) → {req.destination} ({dest_iata}) "
            f"[{req.trip_type}]"
        )

        if settings.RAPIDAPI_KEY and settings.SKYSCANNER_ENABLED:
            try:
                origin_sky, origin_entity = lookup_skyscanner_ids(req.origin, settings.RAPIDAPI_KEY)
                dest_sky, dest_entity     = lookup_skyscanner_ids(req.destination, settings.RAPIDAPI_KEY)
                options = self._search_skyscanner(
                    origin_sky, origin_entity, dest_sky, dest_entity,
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

        plan.flight_options  = options
        plan.selected_flight = self._select_best(options, req.budget_usd)
        plan.mark_complete(self.name)
        return plan

    # ── Skyscanner API ───────────────────────────────────────────────────

    def _search_skyscanner(
        self,
        origin_sky: str, origin_entity: str,
        dest_sky: str, dest_entity: str,
        origin_city: str, dest_city: str,
        depart_date: date, return_date: date,
        adults: int, trip_type: str,
    ) -> list[FlightOption]:
        headers = {
            "x-rapidapi-key":  settings.RAPIDAPI_KEY,
            "x-rapidapi-host": self.RAPIDAPI_HOST,
        }

        # ── Phase 1: start the search ────────────────────────────────────
        params = {
            "originSkyId":         origin_sky,
            "originEntityId":      origin_entity,
            "destinationSkyId":    dest_sky,
            "destinationEntityId": dest_entity,
            "date":                depart_date.isoformat(),
            "adults":              adults,
            "childrens":           0,
            "infants":             0,
            "cabinClass":          "economy",
            "currency":            "USD",
            "countryCode":         "US",
            "market":              "US",
        }
        if trip_type == "roundtrip":
            params["returnDate"] = return_date.isoformat()

        response = httpx.get(
            f"https://{self.RAPIDAPI_HOST}/flights/searchFlights",
            headers=headers, params=params, timeout=30,
        )
        response.raise_for_status()
        raw = response.json()

        session_token = raw.get("sessionToken")
        itineraries   = raw.get("itineraries", [])
        status        = raw.get("status", "")

        self.logger.info(
            f"Initial search: status={status}, "
            f"itineraries={len(itineraries)}, token={'yes' if session_token else 'no'}"
        )

        # ── Phase 2: poll until results populate ─────────────────────────
        MAX_POLLS   = 6
        POLL_WAIT_S = 2.0

        poll = 0
        while not itineraries and session_token and poll < MAX_POLLS:
            poll += 1
            time.sleep(POLL_WAIT_S)
            self.logger.info(f"Polling for results (attempt {poll}/{MAX_POLLS})")

            poll_response = httpx.get(
                f"https://{self.RAPIDAPI_HOST}/flights/searchIncomplete",
                headers=headers,
                params={
                    "sessionId":   session_token,
                    "countryCode": "US",
                    "currency":    "USD",
                },
                timeout=15,
            )
            poll_response.raise_for_status()
            poll_raw = poll_response.json()

            itineraries   = poll_raw.get("itineraries", [])
            status        = poll_raw.get("status", "")
            # token may refresh between polls
            session_token = poll_raw.get("sessionToken", session_token)

            self.logger.info(
                f"Poll {poll}: status={status}, itineraries={len(itineraries)}"
            )

            if itineraries:
                raw = poll_raw  # use the populated response for parsing
                break

        return self._parse_skyscanner(
            raw, origin_city, dest_city,
            depart_date, return_date, adults, trip_type,
        )

    def _parse_skyscanner(
        self, raw: dict,
        origin_city: str, dest_city: str,
        depart_date: date, return_date: date,
        adults: int, trip_type: str,
    ) -> list[FlightOption]:
        options: list[FlightOption] = []
        itineraries = raw.get("itineraries", [])

        if not itineraries:
            raise ValueError(
                f"Skyscanner returned no parseable itineraries "
                f"(status={raw.get('status')}, total={raw.get('total')})."
            )

        for it in itineraries[:10]:
            try:
                price = float(it.get("price", {}).get("amount", 0))
                raw_legs = it.get("legs", [])
                if not raw_legs:
                    continue

                flight_legs = []
                for leg in raw_legs:
                    flight_legs.append(FlightLeg(
                        airline        = leg.get("carriers", [{}])[0].get("name", "Unknown"),
                        origin         = leg.get("origin", ""),
                        destination    = leg.get("destination", ""),
                        departure_time = leg.get("departure", "")[:16],
                        arrival_time   = leg.get("arrival", "")[:16],
                        duration_hours = round(leg.get("durationMinutes", 0) / 60, 1),
                    ))
                
                options.append(FlightOption(
                    trip_type   = trip_type,
                    legs        = flight_legs,
                    price_usd   = price,
                    booking_url = it.get("bookingUrl", ""),
                ))
            except Exception as e:
                self.logger.warning(f"Skipping itinerary: {e}")
        if not options:
            raise ValueError(
                f"Skyscanner returned no parseable itineraries "
                f"(status={raw.get('status')}, total={raw.get('total')}). "
                f"Likely async polling required."
            )
        return options

    # ── Booking URL ──────────────────────────────────────────────────────

    def _build_booking_url(
        self, origin_city: str, dest_city: str,
        depart_date: date, return_date: date,
        trip_type: str, adults: int,
    ) -> str:
        # Skyscanner deep links are built from city codes. For a city in
        # neither lookup table, city_to_skyscanner_code falls back to
        # city.upper()[:3] — a plausible-looking WRONG code that yields a
        # well-formed URL landing on the wrong route. A guessed deep link is
        # worse than no deep link, so degrade to a text search instead.
        #
        # Skyscanner has no stable text-query URL, so there is no partial deep
        # link to fall back to — the homepage is the honest answer. Improving
        # this means adding the city to the lookup tables, which is a real fix
        # rather than a guess.
        if not (has_skyscanner_code(origin_city) and has_skyscanner_code(dest_city)):
            return "https://www.skyscanner.com/"

        orig = city_to_skyscanner_code(origin_city).lower() + "a"
        dest = city_to_skyscanner_code(dest_city).lower() + "a"
        dep  = depart_date.strftime("%y%m%d")

        if trip_type == "one_way":
            return (f"https://www.skyscanner.com/transport/flights/"
                    f"{orig}/{dest}/{dep}/?adultsv2={adults}&cabinclass=economy&rtn=0")
        elif trip_type == "roundtrip":
            ret = return_date.strftime("%y%m%d")
            return (f"https://www.skyscanner.com/transport/flights/"
                    f"{orig}/{dest}/{dep}/{ret}/?adultsv2={adults}&cabinclass=economy&rtn=1")
        else:
            return "https://www.skyscanner.com/flights-multi-city.aspx"

    # ── Mock data ────────────────────────────────────────────────────────

    def _mock_flights(
        self, origin: str, destination: str,
        depart_date: date, return_date: date,
        trip_type: str, budget: float, travelers: int,
    ) -> list[FlightOption]:
        base_price, base_dur = self._estimate_route(origin, destination)
        airlines = ["Air Canada", "Japan Airlines", "ANA",
                    "United Airlines", "British Airways",
                    "Cathay Pacific", "Korean Air"]
        options = []

        for i in range(5):
            mult    = random.uniform(0.85, 1.20)
            dur     = round(base_dur + random.uniform(-1.5, 1.5), 1)
            dep_h   = 8 + (i * 3)
            airline = airlines[i % len(airlines)]

            dep_dt = datetime(depart_date.year, depart_date.month, depart_date.day, dep_h, 0)
            arr_dt = dep_dt + timedelta(hours=dur)

            outbound = FlightLeg(
                airline=airline, origin=origin, destination=destination,
                departure_time=dep_dt.strftime("%Y-%m-%dT%H:%M"),
                arrival_time=arr_dt.strftime("%Y-%m-%dT%H:%M"),
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
                        airline=airline, origin=destination, destination=origin,
                        departure_time=ret_dep.strftime("%Y-%m-%dT%H:%M"),
                        arrival_time=ret_arr.strftime("%Y-%m-%dT%H:%M"),
                        duration_hours=dur,
                    ),
                ]
                price = round(base_price * 1.85 * mult * travelers, 2)
            else:
                legs  = [outbound]
                price = round(base_price * 1.5 * mult * travelers, 2)

            options.append(FlightOption(
                trip_type=trip_type, legs=legs, price_usd=price,
                booking_url=self._build_booking_url(
                    origin, destination, depart_date, return_date, trip_type, travelers,
                ),
            ))
        return options

    def _estimate_route(self, origin: str, dest: str) -> tuple[float, float]:
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

    def _select_best(self, options: list[FlightOption], budget_usd: float) -> FlightOption | None:
        if not options:
            return None
        flight_budget = budget_usd * 0.40
        affordable    = [f for f in options if f.price_usd <= flight_budget]
        candidates    = affordable if affordable else options
        return min(candidates, key=lambda f: f.price_usd)