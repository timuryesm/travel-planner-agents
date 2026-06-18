from __future__ import annotations
import httpx
import random
from datetime import date
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, HotelOption
from src.config.settings import settings


# Booking.com property_type_id values for API filtering
PROPERTY_TYPE_IDS: dict[str, int] = {
    "hotel":      204,
    "apartment":  201,
    "hostel":     203,
    "villa":      213,
    "resort":     220,
    "guesthouse": 208,
}


class HotelAgent(BaseAgent):

    name = "hotels"
    RAPIDAPI_HOST = "apidojo-booking-v1.p.rapidapi.com"

    def run(self, plan: TravelPlan) -> TravelPlan:
        req    = plan.request
        nights = (req.return_date - req.departure_date).days
        acc    = req.accommodation_type

        self.logger.info(
            f"{req.destination} · {nights} nights · "
            f"{req.travelers} guest(s) · type: {acc}"
        )

        if settings.RAPIDAPI_KEY:
            try:
                dest_id = self._get_destination_id(req.destination)
                options = self._search_hotels(
                    dest_id, req.destination,
                    req.departure_date, req.return_date,
                    req.travelers, nights, acc,
                )
                self.logger.info(f"Booking.com returned {len(options)} options")
            except Exception as e:
                self.logger.warning(f"Booking.com failed ({e}) — using mock data")
                options = self._mock_hotels(
                    req.destination, req.departure_date,
                    req.return_date, nights, req.budget_usd, acc,
                )
        else:
            self.logger.info("No RapidAPI key — using mock accommodation data")
            options = self._mock_hotels(
                req.destination, req.departure_date,
                req.return_date, nights, req.budget_usd, acc,
            )

        existing            = plan.hotel_options or []
        plan.hotel_options   = existing + options
        plan.selected_hotel  = self._select_best(plan.hotel_options, req.budget_usd)
        plan.mark_complete(self.name)
        return plan

    # ── Booking.com API ──────────────────────────────────────────────────

    def _get_destination_id(self, city: str) -> str:
        response = httpx.get(
            f"https://{self.RAPIDAPI_HOST}/locations/auto-complete",
            headers={
                "X-RapidAPI-Key":  settings.RAPIDAPI_KEY,
                "X-RapidAPI-Host": self.RAPIDAPI_HOST,
            },
            params={"text": city, "languagecode": "en-us"},
            timeout=10,
        )
        response.raise_for_status()
        results = response.json()

        self.logger.warning(f"Booking.com auto-complete raw response for '{city}': {results}")

        if not results:
            raise ValueError(f"No Booking.com destination found for '{city}'")

        for r in results:
            if r.get("dest_type") == "city":
                self.logger.info(f"Destination ID: {r['dest_id']} ({r.get('label', city)})")
                return str(r["dest_id"])

        return str(results[0]["dest_id"])

    def _search_hotels(
        self,
        dest_id: str,
        destination: str,
        checkin: date,
        checkout: date,
        adults: int,
        nights: int,
        accommodation_type: str,
    ) -> list[HotelOption]:
        params: dict = {
            "dest_id":        dest_id,
            "dest_type":      "city",
            "arrival_date":   checkin.isoformat(),
            "departure_date": checkout.isoformat(),
            "adults_number":  adults,
            "room_number":    1,
            "units":          "metric",
            "locale":         "en-gb",
            "currency_code":  "USD",
        }
        if accommodation_type != "any" and accommodation_type in PROPERTY_TYPE_IDS:
            params["property_type_id"] = PROPERTY_TYPE_IDS[accommodation_type]

        response = httpx.get(
            f"https://{self.RAPIDAPI_HOST}/properties/list",
            headers={
                "X-RapidAPI-Key":  settings.RAPIDAPI_KEY,
                "X-RapidAPI-Host": self.RAPIDAPI_HOST,
            },
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        return self._parse_hotels(
            response.json(), destination, checkin, checkout,
            adults, nights, accommodation_type,
        )

    def _parse_hotels(
        self,
        raw: dict,
        destination: str,
        checkin: date,
        checkout: date,
        adults: int,
        nights: int,
        accommodation_type: str,
    ) -> list[HotelOption]:
        options: list[HotelOption] = []
        hotels = raw.get("result", [])

        if not hotels:
            self.logger.warning(f"Booking.com error response: {raw}")

        for h in hotels[:10]:
            try:
                name        = h.get("hotel_name", "Unknown Hotel")
                stars       = h.get("class")
                total_price = float(h.get("min_total_price", 0))

                if total_price <= 0:
                    continue

                per_night = round(total_price / nights, 2) if nights > 0 else total_price

                options.append(HotelOption(
                    name=name,
                    location=h.get("address", destination),
                    stars=float(stars) if stars else None,
                    price_per_night_usd=per_night,
                    total_price_usd=round(total_price, 2),
                    booking_url=self._build_booking_url(
                        destination, checkin, checkout, adults, accommodation_type
                    ),
                    property_type=accommodation_type if accommodation_type != "any" else "hotel",
                    provider="booking.com",
                ))
            except Exception as e:
                self.logger.warning(f"Skipping property: {e}")

        return options

    # ── Booking URL ──────────────────────────────────────────────────────

    def _build_booking_url(
        self,
        destination: str,
        checkin: date,
        checkout: date,
        adults: int,
        accommodation_type: str = "any",
    ) -> str:
        city = destination.replace(" ", "+")
        url  = (
            f"https://www.booking.com/searchresults.html"
            f"?ss={city}"
            f"&checkin={checkin.isoformat()}"
            f"&checkout={checkout.isoformat()}"
            f"&group_adults={adults}"
            f"&no_rooms=1"
            f"&order=price"
        )
        if accommodation_type != "any" and accommodation_type in PROPERTY_TYPE_IDS:
            url += f"&nflt=property_type%3D{PROPERTY_TYPE_IDS[accommodation_type]}"
        return url

    # ── Mock data ────────────────────────────────────────────────────────

    MOCK_TEMPLATES: dict[str, list[dict]] = {
        "hotel": [
            {"label": "Budget Hotel",      "stars": 2.0, "mult": 0.40},
            {"label": "Business Hotel",    "stars": 3.0, "mult": 0.65},
            {"label": "Comfort Hotel",     "stars": 3.5, "mult": 0.90},
            {"label": "Superior Hotel",    "stars": 4.0, "mult": 1.20},
            {"label": "Deluxe Hotel",      "stars": 4.5, "mult": 1.80},
            {"label": "Luxury Hotel",      "stars": 5.0, "mult": 3.00},
        ],
        "apartment": [
            {"label": "Studio Apartment",      "stars": None, "mult": 0.45},
            {"label": "1-Bed Apartment",       "stars": None, "mult": 0.65},
            {"label": "2-Bed Apartment",       "stars": None, "mult": 0.90},
            {"label": "Serviced Apartment",    "stars": 4.0,  "mult": 1.10},
            {"label": "Luxury Apartment",      "stars": 4.5,  "mult": 1.60},
        ],
        "hostel": [
            {"label": "Backpacker Hostel",     "stars": None, "mult": 0.12},
            {"label": "Social Hostel",         "stars": None, "mult": 0.18},
            {"label": "Boutique Hostel",       "stars": None, "mult": 0.28},
            {"label": "Premium Hostel",        "stars": None, "mult": 0.35},
        ],
        "villa": [
            {"label": "Garden Villa",          "stars": 4.0, "mult": 1.80},
            {"label": "Pool Villa",            "stars": 4.5, "mult": 2.50},
            {"label": "Luxury Villa",          "stars": 5.0, "mult": 4.00},
        ],
        "resort": [
            {"label": "Beach Resort",          "stars": 3.5, "mult": 1.20},
            {"label": "Mountain Resort",       "stars": 4.0, "mult": 1.60},
            {"label": "Luxury Resort",         "stars": 5.0, "mult": 3.50},
        ],
        "guesthouse": [
            {"label": "Family Guesthouse",      "stars": None, "mult": 0.30},
            {"label": "Traditional Guesthouse", "stars": None, "mult": 0.40},
            {"label": "Boutique Guesthouse",    "stars": 3.0,  "mult": 0.55},
        ],
    }

    def _mock_hotels(
        self,
        destination: str,
        checkin: date,
        checkout: date,
        nights: int,
        budget: float,
        accommodation_type: str = "any",
    ) -> list[HotelOption]:
        base      = self._city_price_base(destination)
        districts = self._city_districts(destination)

        if accommodation_type == "any":
            templates = (
                self.MOCK_TEMPLATES["hostel"][:1]
                + self.MOCK_TEMPLATES["apartment"][:2]
                + self.MOCK_TEMPLATES["hotel"]
            )
            types = (
                ["hostel"]
                + ["apartment"] * 2
                + ["hotel"] * len(self.MOCK_TEMPLATES["hotel"])
            )
        else:
            templates = self.MOCK_TEMPLATES.get(
                accommodation_type, self.MOCK_TEMPLATES["hotel"]
            )
            types = [accommodation_type] * len(templates)

        options: list[HotelOption] = []
        for i, (tmpl, prop_type) in enumerate(zip(templates, types)):
            per_night = round(base * tmpl["mult"] * random.uniform(0.9, 1.1), 2)
            total     = round(per_night * nights, 2)
            district  = districts[i % len(districts)]

            options.append(HotelOption(
                name=f"{district} {tmpl['label']}",
                location=f"{district}, {destination}",
                stars=tmpl["stars"],
                price_per_night_usd=per_night,
                total_price_usd=total,
                booking_url=self._build_booking_url(
                    destination, checkin, checkout, 1, accommodation_type
                ),
                property_type=prop_type,
                provider="booking.com",
            ))

        return options

    # ── Helpers ──────────────────────────────────────────────────────────

    def _city_price_base(self, destination: str) -> float:
        prices = {
            "tokyo": 130, "osaka": 100, "kyoto": 110,
            "london": 180, "paris": 170, "amsterdam": 160,
            "new york": 220, "los angeles": 170, "san francisco": 200,
            "sydney": 150, "dubai": 160, "singapore": 170,
            "bangkok": 60, "istanbul": 80, "berlin": 110,
            "barcelona": 130, "rome": 120, "toronto": 140,
        }
        return prices.get(destination.lower(), 120)

    def _city_districts(self, destination: str) -> list[str]:
        districts = {
            "tokyo":    ["Shinjuku", "Shibuya", "Ginza", "Asakusa", "Akihabara", "Roppongi"],
            "london":   ["Covent Garden", "Soho", "Mayfair", "Shoreditch", "Kensington", "South Bank"],
            "paris":    ["Le Marais", "Saint-Germain", "Montmartre", "Bastille", "Opéra", "Champs-Élysées"],
            "new york": ["Midtown", "SoHo", "Brooklyn", "Upper East Side", "Chelsea", "Times Square"],
            "toronto":  ["Downtown", "Yorkville", "King West", "Distillery", "Harbourfront", "Kensington"],
        }
        return districts.get(
            destination.lower(),
            ["City Centre", "Old Town", "Downtown", "Harbour", "North District", "South District"],
        )

    def _select_best(
        self, options: list[HotelOption], budget_usd: float
    ) -> HotelOption | None:
        if not options:
            return None
        hotel_budget = budget_usd * 0.35
        affordable   = [h for h in options if h.total_price_usd <= hotel_budget]
        candidates   = affordable if affordable else options
        return max(candidates, key=lambda h: (h.stars or 0, -h.total_price_usd))