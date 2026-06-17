from __future__ import annotations
import httpx
import random
from datetime import date
from src.agents.base_agent import BaseAgent
from src.state.travel_plan import TravelPlan, HotelOption
from src.config.settings import settings


class AirbnbAgent(BaseAgent):

    name = "airbnb"
    RAPIDAPI_HOST = "airbnb19.p.rapidapi.com"

    # Airbnb room types with display labels
    ROOM_TYPES = {
        "private_room":   "Private Room",
        "entire_home":    "Entire Apartment",
        "entire_house":   "Entire House",
        "shared_room":    "Shared Room",
    }

    def run(self, plan: TravelPlan) -> TravelPlan:
        req    = plan.request
        nights = (req.return_date - req.departure_date).days

        self.logger.info(
            f"Airbnb · {req.destination} · {nights} nights · "
            f"{req.travelers} guest(s) · type: {req.accommodation_type}"
        )

        if settings.RAPIDAPI_KEY:
            try:
                options = self._search_airbnb(req, nights)
                self.logger.info(f"Airbnb returned {len(options)} listings")
            except Exception as e:
                self.logger.warning(f"Airbnb API failed ({e}) — using mock data")
                options = self._mock_listings(
                    req.destination, req.departure_date,
                    req.return_date, nights,
                    req.budget_usd, req.accommodation_type,
                )
        else:
            self.logger.info("No RapidAPI key — using mock Airbnb data")
            options = self._mock_listings(
                req.destination, req.departure_date,
                req.return_date, nights,
                req.budget_usd, req.accommodation_type,
            )

        # Append to existing results (don't overwrite Booking.com results)
        existing           = plan.hotel_options or []
        plan.hotel_options = existing + options

        # Re-select best across ALL providers combined
        plan.selected_hotel = self._select_best(plan.hotel_options, req.budget_usd)
        plan.mark_complete(self.name)
        return plan

    # ── Airbnb API ───────────────────────────────────────────────────────

    def _search_airbnb(self, req, nights: int) -> list[HotelOption]:
        response = httpx.get(
            f"https://{self.RAPIDAPI_HOST}/search",
            headers={
                "X-RapidAPI-Key":  settings.RAPIDAPI_KEY,
                "X-RapidAPI-Host": self.RAPIDAPI_HOST,
            },
            params={
                "location":  req.destination,
                "checkin":   req.departure_date.isoformat(),
                "checkout":  req.return_date.isoformat(),
                "adults":    req.travelers,
                "children":  0,
                "infants":   0,
                "pets":      0,
                "page":      1,
                "currency":  "USD",
            },
            timeout=15,
        )
        response.raise_for_status()
        return self._parse_airbnb(
            response.json(),
            req.destination,
            req.departure_date,
            req.return_date,
            req.travelers,
            nights,
        )

    def _parse_airbnb(
        self,
        raw: dict,
        destination: str,
        checkin: date,
        checkout: date,
        adults: int,
        nights: int,
    ) -> list[HotelOption]:
        """
        Parse Airbnb API response. Handles two common response structures
        from different Airbnb API versions on RapidAPI.
        """
        options: list[HotelOption] = []

        # Structure 1: {"results": [...]}
        listings = raw.get("results", [])

        # Structure 2: {"listings": [{"listing": {...}, "pricing_quote": {...}}]}
        if not listings and "listings" in raw:
            listings = raw["listings"]

        for item in listings[:10]:
            try:
                # Handle both flat and nested structures
                listing = item.get("listing", item)
                pricing = item.get("pricing_quote", {})

                name      = listing.get("name", "Airbnb Listing")
                room_type = listing.get("room_type_category") or \
                            listing.get("type", "entire_home")
                listing_id = str(listing.get("id", ""))
                rating    = listing.get("avg_rating") or listing.get("rating")

                # Price — check multiple locations
                price_block = listing.get("price") or pricing
                total_price = (
                    price_block.get("total")
                    or price_block.get("localized_total_price")
                    or (price_block.get("rate", {}).get("amount", 0) * nights
                        if isinstance(price_block.get("rate"), dict)
                        else 0)
                )
                if not total_price:
                    continue

                total_price = float(total_price)
                per_night   = round(total_price / nights, 2)

                # Convert room_type to readable label
                label = self.ROOM_TYPES.get(
                    room_type.lower().replace(" ", "_"),
                    room_type.replace("_", " ").title()
                )

                booking_url = (
                    f"https://www.airbnb.com/rooms/{listing_id}"
                    f"?checkin={checkin}&checkout={checkout}&adults={adults}"
                    if listing_id else
                    self._build_search_url(destination, checkin, checkout, adults)
                )

                # Map star rating: Airbnb uses 5-star scale
                stars = round(float(rating) / 1.0, 1) if rating else None

                options.append(HotelOption(
                    name=name,
                    location=destination,
                    stars=stars,
                    price_per_night_usd=per_night,
                    total_price_usd=round(total_price, 2),
                    booking_url=booking_url,
                    property_type=label,
                    provider="airbnb",
                ))
            except Exception as e:
                self.logger.warning(f"Skipping listing: {e}")

        return options

    # ── Booking URL ──────────────────────────────────────────────────────

    def _build_search_url(
        self,
        destination: str,
        checkin: date,
        checkout: date,
        adults: int,
    ) -> str:
        city = destination.replace(" ", "--") + "--Japan"   # works for Tokyo
        return (
            f"https://www.airbnb.com/s/{city}/homes"
            f"?checkin={checkin}&checkout={checkout}"
            f"&adults={adults}"
            f"&tab_id=home_tab"
        )

    # ── Mock data ────────────────────────────────────────────────────────

    MOCK_LISTING_TYPES: list[dict] = [
        {"type": "Shared Room",        "room_cat": "shared_room",   "stars": 4.2, "mult": 0.15},
        {"type": "Private Room",       "room_cat": "private_room",  "stars": 4.5, "mult": 0.30},
        {"type": "Private Room",       "room_cat": "private_room",  "stars": 4.7, "mult": 0.40},
        {"type": "Entire Studio",      "room_cat": "entire_home",   "stars": 4.6, "mult": 0.60},
        {"type": "Entire 1-Bed Apt",   "room_cat": "entire_home",   "stars": 4.8, "mult": 0.85},
        {"type": "Entire 2-Bed Apt",   "room_cat": "entire_home",   "stars": 4.7, "mult": 1.20},
        {"type": "Entire House",       "room_cat": "entire_house",  "stars": 4.9, "mult": 1.80},
    ]

    def _mock_listings(
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

        # Filter by accommodation type if specified
        if accommodation_type == "apartment":
            templates = [t for t in self.MOCK_LISTING_TYPES
                         if "Apt" in t["type"] or "Studio" in t["type"]]
        elif accommodation_type == "hostel":
            templates = [t for t in self.MOCK_LISTING_TYPES
                         if "Shared" in t["type"] or "Private Room" in t["type"]]
        elif accommodation_type == "villa":
            templates = [t for t in self.MOCK_LISTING_TYPES
                         if "House" in t["type"]]
        else:
            templates = self.MOCK_LISTING_TYPES

        neighbourhood_names = [
            "Cozy", "Modern", "Spacious", "Charming",
            "Central", "Quiet", "Stylish", "Traditional",
        ]

        options: list[HotelOption] = []
        for i, tmpl in enumerate(templates):
            per_night = round(base * tmpl["mult"] * random.uniform(0.88, 1.12), 2)
            total     = round(per_night * nights, 2)
            district  = districts[i % len(districts)]
            adj       = neighbourhood_names[i % len(neighbourhood_names)]
            name      = f"{adj} {tmpl['type']} in {district}"

            options.append(HotelOption(
                name=name,
                location=f"{district}, {destination}",
                stars=tmpl["stars"],
                price_per_night_usd=per_night,
                total_price_usd=total,
                booking_url=self._build_search_url(
                    destination, checkin, checkout, 1
                ),
                property_type=tmpl["type"],
                provider="airbnb",
            ))

        return options

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
            "tokyo":    ["Shinjuku", "Shibuya", "Shimokitazawa",
                         "Yanaka", "Nakameguro", "Asakusa", "Koenji"],
            "london":   ["Shoreditch", "Hackney", "Notting Hill",
                         "Brixton", "Islington", "Dalston", "Peckham"],
            "paris":    ["Le Marais", "Belleville", "Canal Saint-Martin",
                         "Batignolles", "Oberkampf", "Montmartre"],
            "new york": ["Williamsburg", "Astoria", "Park Slope",
                         "Harlem", "Long Island City", "Bushwick"],
            "toronto":  ["Kensington", "Little Portugal", "Leslieville",
                         "Parkdale", "The Annex", "Roncesvalles"],
        }
        return districts.get(
            destination.lower(),
            ["City Centre", "Old Town", "Riverside",
             "Arts District", "University Area", "Market Quarter"],
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