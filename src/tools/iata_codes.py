# Major city → primary airport IATA code
CITY_TO_IATA: dict[str, str] = {
    "toronto": "YYZ", "new york": "JFK", "london": "LHR",
    "paris": "CDG", "tokyo": "NRT", "osaka": "KIX",
    "sydney": "SYD", "dubai": "DXB", "singapore": "SIN",
    "amsterdam": "AMS", "frankfurt": "FRA", "bangkok": "BKK",
    "hong kong": "HKG", "barcelona": "BCN", "rome": "FCO",
    "madrid": "MAD", "berlin": "BER", "istanbul": "IST",
    "los angeles": "LAX", "chicago": "ORD", "miami": "MIA",
    "san francisco": "SFO", "seattle": "SEA", "boston": "BOS",
    "vancouver": "YVR", "montreal": "YUL", "mexico city": "MEX",
    "seoul": "ICN", "beijing": "PEK", "shanghai": "PVG",
    "mumbai": "BOM", "delhi": "DEL", "cairo": "CAI",
    "johannesburg": "JNB", "nairobi": "NBO", "lagos": "LOS",
    "buenos aires": "EZE", "sao paulo": "GRU", "lima": "LIM",
}


def city_to_iata(city: str) -> str:
    """Convert a city name to its primary airport IATA code."""
    code = CITY_TO_IATA.get(city.lower().strip())
    if not code:
        raise ValueError(
            f"No IATA code found for '{city}'. "
            f"Add it to src/tools/iata_codes.py or use the code directly."
        )
    return code