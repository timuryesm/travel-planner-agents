"""
Geocoding lookup — cached, rate-limited access to Nominatim.

Why this module exists
----------------------
WeatherAgent geocoded its hub city on every run, with a fresh Nominatim client
each time. Nominatim is free, unkeyed, and its usage policy allows at most one
request per second from a single application; it enforces that with 403s and
temporary blocks, not polite warnings.

The request pattern made that easy to hit. React 18 StrictMode double-invokes
effects, so a daily-plan stage mount fires two weather calls; each one geocoded
the same city again. `uvicorn --reload` restarts the process on every file
save, so any in-process memoisation was worthless during development — the same
shape of problem advisory_lookup had before its cache moved to disk.

The fix is the same shape, with one important difference: advisories change, so
that cache has a TTL. **Coordinates do not.** Tokyo will be at 35.68N, 139.65E
for the lifetime of this project, so a successful geocode is kept indefinitely
and a deployed instance geocodes each city exactly once, ever.

What is NOT cached
------------------
Failures. A miss can mean "no such place" (permanent) or "you are being rate
limited" (transient), and the two are indistinguishable from the response. A
permanent-looking negative cache built from a transient block would poison
every future lookup for that city. Instead there is a short in-memory backoff
per city, long enough to stop a retry loop, short enough to forget a blip.

Ambiguity
---------
Nominatim resolves a bare name to its most prominent match, so "Cambridge"
lands in England, not Massachusetts. The caller passes a `country` hint when it
has one — the trip always knows its country, even though TravelRequest doesn't
currently carry it — and the hint is part of the cache key, so adding it later
does not silently serve a previous unqualified answer.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Optional

from geopy.geocoders import Nominatim

logger = logging.getLogger("geocode_lookup")

# Nominatim's policy: one request per second, and a User-Agent that identifies
# the application. A generic or absent UA is the documented way to get blocked.
_MIN_INTERVAL_S = 1.1          # a little over 1s — the limit is a floor, not a target
_USER_AGENT = "travel-planner-agents/1.0 (github.com/timuryesm/travel-planner-agents)"
_TIMEOUT_S = 10.0

# After a failed lookup for a given city, don't try that city again for this
# long. Process-local and monotonic: it is about this process's recent
# behaviour, not about the data.
_FAILURE_BACKOFF_S = 5 * 60

# Bumped when the cache format changes, so an old file is ignored rather than
# misread. Cheaper than a migration for something that costs one HTTP request
# to rebuild.
_CACHE_VERSION = 1

_CACHE_PATH = Path(
    os.environ.get("GEOCODE_CACHE_PATH")
    or Path(tempfile.gettempdir()) / "travel_planner_geocode.json"
)

# key ("tokyo" or "cambridge|united kingdom") → [lat, lon]
_coords: dict[str, tuple[float, float]] = {}
_failed_at: dict[str, float] = {}   # key → time.monotonic() of last failure
_last_request_at: float = 0.0       # monotonic; the rate-limit gate
_disk_checked: bool = False


class GeocodeError(RuntimeError):
    """
    A city could not be geocoded.

    A distinct type so callers can tell "we could not find this place" from a
    programming error. WeatherAgent lets it propagate; safe_run turns it into a
    degraded forecast, which is the honest outcome — a plan with no weather
    lines rather than a plan with invented ones.
    """


# ── Key handling ─────────────────────────────────────────────────────────────

def _key(city: str, country: Optional[str]) -> str:
    """
    Normalised cache key. Casefolds and strips accents so "Zürich" and "Zurich"
    are one entry, and includes the country hint when present so a qualified
    lookup never collides with an unqualified one.
    """
    def norm(s: str) -> str:
        decomposed = unicodedata.normalize("NFKD", s)
        ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
        return " ".join(ascii_only.casefold().split())

    base = norm(city)
    return f"{base}|{norm(country)}" if country else base


# ── Disk cache ───────────────────────────────────────────────────────────────

def _load_from_disk() -> None:
    """
    Populate the in-memory map from the cache file.

    Forgiving by design: a missing, truncated, or garbage file is a cache miss.
    Each entry is validated individually — a single corrupt row is dropped
    rather than discarding a cache that is otherwise fine, because rebuilding
    it means one rate-limited request per city.
    """
    global _coords

    try:
        payload = json.loads(_CACHE_PATH.read_text())
        if int(payload.get("version", 0)) != _CACHE_VERSION:
            logger.info(f"Ignoring geocode cache with old format at {_CACHE_PATH}")
            return
        raw = payload["coords"]
        if not isinstance(raw, dict):
            raise ValueError("malformed 'coords'")
    except FileNotFoundError:
        return
    except Exception as e:
        logger.warning(f"Ignoring unreadable geocode cache at {_CACHE_PATH}: {e}")
        return

    loaded: dict[str, tuple[float, float]] = {}
    for key, value in raw.items():
        try:
            lat, lon = float(value[0]), float(value[1])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError(f"out of range: {lat},{lon}")
            loaded[str(key)] = (lat, lon)
        except Exception as e:
            logger.warning(f"Dropping bad geocode cache entry {key!r}: {e}")

    _coords = loaded
    logger.info(f"Geocode cache loaded from disk — {len(loaded)} cities")


def _save_to_disk() -> None:
    """Write atomically. Never raises: failing to cache is not failing to answer."""
    if not _coords:
        return
    try:
        payload = {
            "version": _CACHE_VERSION,
            "coords": {k: [lat, lon] for k, (lat, lon) in _coords.items()},
        }
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, _CACHE_PATH)   # atomic — no half-written cache
    except Exception as e:
        logger.warning(f"Could not write geocode cache to {_CACHE_PATH}: {e}")


# ── Network ──────────────────────────────────────────────────────────────────

def _wait_for_slot() -> None:
    """
    Block until at least _MIN_INTERVAL_S has passed since the last request.

    Crude on purpose. The alternative — a token bucket, or geopy's own
    RateLimiter — buys nothing here: cache hits never reach this function, so
    the only calls that wait are genuinely new cities, and a trip has a
    handful of those at most.
    """
    global _last_request_at
    if _last_request_at:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - elapsed)
    _last_request_at = time.monotonic()


def _fetch(city: str, country: Optional[str]) -> tuple[float, float]:
    query = f"{city}, {country}" if country else city
    _wait_for_slot()
    geolocator = Nominatim(user_agent=_USER_AGENT, timeout=_TIMEOUT_S)
    location = geolocator.geocode(query)
    if not location:
        raise GeocodeError(f"Could not geocode '{query}'")
    return float(location.latitude), float(location.longitude)


# ── Public API ───────────────────────────────────────────────────────────────

def geocode(city: str, country: Optional[str] = None) -> tuple[float, float]:
    """
    Coordinates for a city, from cache when possible.

    Raises GeocodeError when the city cannot be resolved, or when a recent
    failure for the same city is still inside the backoff window. Never
    returns approximate or invented coordinates — a wrong latitude produces a
    confident, wrong forecast, which is worse than no forecast at all.
    """
    global _disk_checked

    if not city or not city.strip():
        raise GeocodeError("No city given")

    if not _disk_checked:
        _disk_checked = True
        _load_from_disk()

    key = _key(city, country)

    hit = _coords.get(key)
    if hit is not None:
        return hit

    # An unqualified entry answers a qualified lookup for the same city: the
    # coordinates came from the same Nominatim resolution either way. The
    # reverse is NOT true — a qualified answer is more specific than the bare
    # name would have produced, so it is stored under its own key only.
    if country:
        bare = _coords.get(_key(city, None))
        if bare is not None:
            return bare

    last_failure = _failed_at.get(key)
    if last_failure and time.monotonic() - last_failure < _FAILURE_BACKOFF_S:
        raise GeocodeError(
            f"Geocoding for '{city}' failed recently; not retrying yet"
        )

    try:
        lat, lon = _fetch(city, country)
    except GeocodeError:
        _failed_at[key] = time.monotonic()
        raise
    except Exception as e:
        # Network error, timeout, or a 403 from exceeding the rate limit. Same
        # backoff — hammering a service that just blocked us is how the block
        # becomes longer.
        _failed_at[key] = time.monotonic()
        raise GeocodeError(f"Geocoding '{city}' failed: {e}") from e

    _coords[key] = (lat, lon)
    _failed_at.pop(key, None)
    logger.info(f"Geocoded '{city}' → {lat:.3f}, {lon:.3f} (cached)")
    _save_to_disk()
    return lat, lon