from __future__ import annotations
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

# Expanded fallback table — covers 100+ major travel destinations
# Used when the Skyscanner API is unavailable or returns no result
IATA_FALLBACK: dict[str, str] = {
    # North America
    "toronto": "YYZ", "new york": "JFK", "new york city": "JFK",
    "los angeles": "LAX", "chicago": "ORD", "miami": "MIA",
    "san francisco": "SFO", "seattle": "SEA", "boston": "BOS",
    "washington": "IAD", "washington dc": "DCA", "atlanta": "ATL",
    "dallas": "DFW", "houston": "IAH", "denver": "DEN",
    "las vegas": "LAS", "orlando": "MCO", "phoenix": "PHX",
    "vancouver": "YVR", "montreal": "YUL", "calgary": "YYC",
    "mexico city": "MEX", "cancun": "CUN",
    # Europe
    "london": "LHR", "paris": "CDG", "amsterdam": "AMS",
    "frankfurt": "FRA", "madrid": "MAD", "barcelona": "BCN",
    "rome": "FCO", "milan": "MXP", "berlin": "BER", "munich": "MUC",
    "zurich": "ZRH", "vienna": "VIE", "brussels": "BRU",
    "lisbon": "LIS", "athens": "ATH", "istanbul": "IST",
    "stockholm": "ARN", "oslo": "OSL", "copenhagen": "CPH",
    "helsinki": "HEL", "dublin": "DUB", "prague": "PRG",
    "budapest": "BUD", "warsaw": "WAW",
    # Asia
    "tokyo": "NRT", "osaka": "KIX", "kyoto": "KIX",
    "seoul": "ICN", "beijing": "PEK", "shanghai": "PVG",
    "hong kong": "HKG", "singapore": "SIN", "bangkok": "BKK",
    "taipei": "TPE", "kuala lumpur": "KUL", "jakarta": "CGK",
    "manila": "MNL", "delhi": "DEL", "mumbai": "BOM",
    "bangalore": "BLR", "dubai": "DXB", "abu dhabi": "AUH",
    "doha": "DOH", "riyadh": "RUH", "tel aviv": "TLV",
    "kathmandu": "KTM", "colombo": "CMB", "karachi": "KHI",
    # Oceania
    "sydney": "SYD", "melbourne": "MEL", "brisbane": "BNE",
    "auckland": "AKL", "perth": "PER",
    # Africa
    "johannesburg": "JNB", "cape town": "CPT", "cairo": "CAI",
    "nairobi": "NBO", "casablanca": "CMN", "lagos": "LOS",
    "addis ababa": "ADD",
    # South America
    "sao paulo": "GRU", "rio de janeiro": "GIG", "buenos aires": "EZE",
    "lima": "LIM", "bogota": "BOG", "santiago": "SCL",
}


def lookup_iata(city: str, rapidapi_key: str = "") -> str:
    """
    Convert a city name to its primary IATA airport code.

    Priority:
      1. Skyscanner airport search API (if key provided)
      2. Built-in table of 100+ major airports
    """
    city_clean = city.strip()

    # 1. Try Skyscanner API
    if rapidapi_key:
        code = _skyscanner_airport_search(city_clean, rapidapi_key)
        if code:
            logger.debug(f"IATA via API: {city} → {code}")
            return code
        logger.debug(f"Skyscanner airport search had no result for '{city}', using fallback")

    # 2. Fall back to built-in table
    code = IATA_FALLBACK.get(city_clean.lower())
    if code:
        logger.debug(f"IATA via fallback table: {city} → {code}")
        return code

    raise ValueError(
        f"Could not find IATA code for '{city}'.\n"
        f"  Add it to IATA_FALLBACK in src/tools/airport_lookup.py\n"
        f"  or use the code directly (e.g. 'NRT' for Tokyo Narita)."
    )


def _skyscanner_airport_search(city: str, key: str) -> Optional[str]:
    """Query the Skyscanner API airport search endpoint."""
    try:
        response = httpx.get(
            "https://skyscanner-flights-travel-api.p.rapidapi.com/api/v1/searchAirport",
            headers={
                "X-RapidAPI-Key":  key,
                "X-RapidAPI-Host": "skyscanner-flights-travel-api.p.rapidapi.com",
            },
            params={"query": city},
            timeout=10,
        )
        response.raise_for_status()
        results = response.json().get("data", [])

        # Prefer an airport entity over a city entity
        for r in results:
            if r.get("entityType", "").upper() == "AIRPORT":
                return r.get("iataCode") or r.get("skyId")

        # Fall back to first result of any type
        if results:
            return results[0].get("iataCode") or results[0].get("skyId")

    except Exception as e:
        logger.debug(f"Skyscanner airport API error: {e}")

    return None


# Skyscanner URLs use city-level codes, not airport codes
# e.g. Toronto = YTO (not YYZ), Tokyo = TYO (not NRT), London = LON (not LHR)
SKYSCANNER_CITY_CODES: dict[str, str] = {
    # North America
    "toronto": "YTO", "new york": "NYC", "new york city": "NYC",
    "chicago": "CHI", "los angeles": "LAX", "san francisco": "SFO",
    "miami": "MIA", "washington": "WAS", "washington dc": "WAS",
    "boston": "BOS", "seattle": "SEA", "denver": "DEN",
    "atlanta": "ATL", "dallas": "DFW", "houston": "HOU",
    "las vegas": "LAS", "orlando": "ORL", "phoenix": "PHX",
    "vancouver": "YVR", "montreal": "YMQ", "calgary": "YYC",
    "mexico city": "MEX", "cancun": "CUN",
    # Europe
    "london": "LON", "paris": "PAR", "amsterdam": "AMS",
    "frankfurt": "FRA", "madrid": "MAD", "barcelona": "BCN",
    "rome": "ROM", "milan": "MIL", "berlin": "BER", "munich": "MUC",
    "zurich": "ZRH", "vienna": "VIE", "brussels": "BRU",
    "lisbon": "LIS", "athens": "ATH", "istanbul": "IST",
    "stockholm": "STO", "oslo": "OSL", "copenhagen": "CPH",
    "helsinki": "HEL", "dublin": "DUB", "prague": "PRG",
    "budapest": "BUD", "warsaw": "WAW",
    # Asia
    "tokyo": "TYO", "osaka": "OSA", "kyoto": "OSA",
    "seoul": "SEL", "beijing": "BJS", "shanghai": "SHA",
    "hong kong": "HKG", "singapore": "SIN", "bangkok": "BKK",
    "taipei": "TPE", "kuala lumpur": "KUL", "jakarta": "JKT",
    "manila": "MNL", "delhi": "DEL", "mumbai": "BOM",
    "dubai": "DXB", "abu dhabi": "AUH", "doha": "DOH",
    # Oceania
    "sydney": "SYD", "melbourne": "MEL", "brisbane": "BNE",
    "auckland": "AKL", "perth": "PER",
    # Africa
    "johannesburg": "JNB", "cape town": "CPT", "cairo": "CAI",
    "nairobi": "NBO",
    # South America
    "sao paulo": "SAO", "rio de janeiro": "RIO", "buenos aires": "BUE",
    "lima": "LIM", "bogota": "BOG", "santiago": "SCL",
}


def city_to_skyscanner_code(city: str) -> str:
    """
    Return the Skyscanner city code used in booking URLs.
    Different from the airport IATA for multi-airport cities:
      Toronto → YTO (not YYZ), Tokyo → TYO (not NRT), London → LON (not LHR)
    """
    code = SKYSCANNER_CITY_CODES.get(city.lower().strip())
    if code:
        return code
    # Single-airport cities: airport IATA works as city code too
    return IATA_FALLBACK.get(city.lower().strip(), city.upper()[:3])


def lookup_skyscanner_ids(city: str, rapidapi_key: str) -> tuple[str, str]:
    """
    Resolve a city name to Skyscanner's internal (skyId, entityId) pair
    via /flights/searchAirport. Prefers the CITY-level result.
    """
    response = httpx.get(
        "https://skyscanner-flights-travel-api.p.rapidapi.com/flights/searchAirport",
        headers={
            "x-rapidapi-key":  rapidapi_key,
            "x-rapidapi-host": "skyscanner-flights-travel-api.p.rapidapi.com",
        },
        params={"query": city, "market": "US", "locale": "en-US"},
        timeout=10,
    )
    response.raise_for_status()
    raw = response.json()

    places = raw.get("places", [])
    if not places:
        logger.warning(f"Skyscanner searchAirport raw response for '{city}': {raw}")
        raise ValueError(f"No Skyscanner airport results for '{city}'")

    # Prefer the CITY-level entry over individual airports
    city_match = next((p for p in places if p.get("placeType") == "CITY"), None)
    chosen = city_match or places[0]

    sky_id    = chosen.get("skyId")
    entity_id = chosen.get("entityId")

    if not sky_id or not entity_id:
        raise ValueError(f"Could not parse skyId/entityId for '{city}'. Got: {chosen}")

    logger.info(f"Skyscanner IDs for '{city}': skyId={sky_id}, entityId={entity_id}")
    return str(sky_id), str(entity_id)