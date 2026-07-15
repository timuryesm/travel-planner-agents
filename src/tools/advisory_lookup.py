"""
Travel-advisory lookup — cached access to the U.S. State Department feed.

Why this module exists
----------------------
The feed at cadataapi.state.gov publishes ONE document containing an advisory
level (1-4) for every country. The naive usage — which DestinationAgent
originally had — was to fetch that whole document once per city and scan it
for a single country name. Six proposed cities meant six full downloads of the
same document per stage load, each thrown away after one lookup. That
rate-limited us into a 429 within a few dev runs, and every safety note
silently degraded to the neutral placeholder.

So: fetch the document at most once per TTL, parse it into a country → level
map, and answer every lookup from memory.

Staleness policy: advisories change on the order of weeks, so a 6-hour TTL is
conservative. If a refresh fails but we hold a previous copy, we serve the
stale copy rather than nothing — hours-old official guidance beats no guidance.
We never fabricate: with no data at all, callers get None and must say so.

Process-local cache. Fine for a single uvicorn worker; if this is ever run
multi-worker each process keeps its own copy, which is still ~1 request per
worker per 6 hours.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

import httpx

logger = logging.getLogger("advisory_lookup")

_FEED_URL = "https://cadataapi.state.gov/api/TravelAdvisories"

_TTL_S = 6 * 60 * 60          # refresh at most every 6 hours
_FAILURE_BACKOFF_S = 5 * 60   # after a failure, don't hammer the API for 5 min
_TIMEOUT_S = 10.0

# State Dept advisory levels → short traveller-facing note
ADVISORY_NOTES: dict[int, str] = {
    1: "Exercise normal precautions.",
    2: "Exercise increased caution.",
    3: "Reconsider travel; check current advisories before booking.",
    4: "Do not travel; this destination is under a severe advisory.",
}

# Parsed feed: list of (lowercased title, level). Kept as titles rather than a
# country→level dict because feed titles aren't clean country names — they look
# like "Mexico - Level 2: Exercise Increased Caution" and sometimes carry
# regional qualifiers. Substring matching against the title is what the
# original code did and it works; we've only removed the repeated downloads.
_entries: Optional[list[tuple[str, int]]] = None
_fetched_at: float = 0.0
_failed_at: float = 0.0


def _parse_level(title: str) -> Optional[int]:
    """'Japan - Level 1: Exercise Normal Precautions' → 1"""
    m = re.search(r"level\s+(\d)", title.lower())
    return int(m.group(1)) if m else None


def _refresh() -> None:
    """Fetch and parse the feed. Leaves previous data intact on failure."""
    global _entries, _fetched_at, _failed_at

    try:
        resp = httpx.get(_FEED_URL, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        _failed_at = time.monotonic()
        if _entries is None:
            logger.warning(f"Advisory feed unavailable and no cached copy: {e}")
        else:
            age_h = (time.monotonic() - _fetched_at) / 3600
            logger.warning(
                f"Advisory feed refresh failed ({e}) — serving cached copy "
                f"({age_h:.1f}h old)"
            )
        return

    parsed: list[tuple[str, int]] = []
    for entry in raw:
        title = entry.get("Title") or ""
        level = _parse_level(title)
        if level is not None:
            parsed.append((title.lower(), level))

    _entries = parsed
    _fetched_at = time.monotonic()
    _failed_at = 0.0
    logger.info(f"Advisory feed refreshed — {len(parsed)} country advisories")


def _ensure_fresh() -> None:
    now = time.monotonic()

    if _entries is not None and now - _fetched_at < _TTL_S:
        return  # cache is good

    if _failed_at and now - _failed_at < _FAILURE_BACKOFF_S:
        return  # recently failed; don't retry yet (this is what stops the 429 loop)

    _refresh()


def advisory_note(country: str) -> Optional[str]:
    """
    Short advisory note for a country, or None if unknown/unavailable.

    None means "we don't know" — callers must NOT substitute a guess.
    """
    if not country:
        return None

    _ensure_fresh()
    if not _entries:
        return None

    country_lc = country.lower()
    for title, level in _entries:
        if country_lc in title:
            return ADVISORY_NOTES.get(level)
    return None