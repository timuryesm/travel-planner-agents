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

How the endpoint actually misbehaves
------------------------------------
Measured July 2026: it does NOT return 429. It returns **200 OK with a two-byte
body — `[]`** — erratically. Observed within one hour: a full 703 KB response;
an empty one 32 minutes later; a full one 5 minutes after that; then five empty
ones three seconds apart. The pattern is not a clean cooldown and not obviously
time-based — successes and empties interleave on the scale of minutes.

So the failure mode is an empty success, which is the most dangerous shape a
failure can take: `[]` parses fine, and a naive implementation caches it as "no
advisories exist anywhere" for a full TTL, degrading every safety note to a
placeholder without a single warning line.

Since a retry might succeed but a burst clearly doesn't, the answer is not
cleverness at fetch time — it is to keep any successful fetch for a long time
(the disk cache below) and to never mistake `[]` for data.

An empty array is therefore treated as a FAILURE here, never as data.

Staleness policy: advisories change on the order of weeks, so a 6-hour TTL is
conservative. If a refresh fails but we hold a previous copy, we serve the
stale copy rather than nothing — hours-old official guidance beats no guidance.
We never fabricate: with no data at all, callers get None and must say so.

Why the cache is on disk
------------------------
It used to be process-local, which is the same as no cache under
`uvicorn --reload`: every file save restarts the process, drops the map, and
sends the next country stage load straight back to an endpoint that returns
`[]` a good fraction of the time. Persisting the parsed map means the TTL is a
property of the DATA, not of the process — a restart mid-cooldown serves the
previous copy, which is exactly the staleness policy above, applied across the
one boundary that was breaking it. In production it also collapses N workers'
fetches into one.

Persisted age uses wall-clock time, since time.monotonic() is meaningless
across restarts. The failure backoff stays monotonic: it is about this
process's recent behaviour, not about the data's age.

Three things this module gets deliberately right
------------------------------------------------
1. FETCH AND PARSE ARE BOTH INSIDE THE FAILURE PATH. An earlier version parsed
   outside the try, so an unexpected feed shape raised straight through
   _refresh() and advisory_note() into the agent's safe_run(), which turned it
   into a 200 with an empty options list — and, because _failed_at was never
   set, left no backoff, so the next request re-downloaded the feed.

2. MATCHING IS BY NAME, NOT BY SUBSTRING. An earlier version asked
   `country.lower() in title.lower()`, which is true for ("Oman", "Romania"),
   ("Mali", "Somalia"), ("Niger", "Nigeria") and ("Guinea", "Papua New
   Guinea"). Attaching Somalia's Level 4 to Mali is a worse failure than
   attaching nothing, and it is silent.

3. AMBIGUITY RESOLVES TO None, NOT TO A COIN FLIP. The word-boundary fallback
   exists for titles the exact match can't reach, but if it hits more than one
   entry we have no principled way to choose, and choosing by dict order is
   choosing by luck.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger("advisory_lookup")

_FEED_URL = "https://cadataapi.state.gov/api/TravelAdvisories"

_TTL_S = 6 * 60 * 60          # refresh at most every 6 hours
_FAILURE_BACKOFF_S = 5 * 60   # after a failure, don't retry for 5 min
_TIMEOUT_S = 10.0

# Where the parsed map is persisted between runs. Override with
# ADVISORY_CACHE_PATH if you want it inside the repo or a mounted volume;
# the temp dir is the right default because this is a cache — losing it costs
# one HTTP request, never correctness.
_CACHE_PATH = Path(
    os.environ.get("ADVISORY_CACHE_PATH")
    or Path(tempfile.gettempdir()) / "travel_planner_advisories.json"
)

# State Dept advisory levels → short traveller-facing note
ADVISORY_NOTES: dict[int, str] = {
    1: "Exercise normal precautions.",
    2: "Exercise increased caution.",
    3: "Reconsider travel; check current advisories before booking.",
    4: "Do not travel; this destination is under a severe advisory.",
}

# Parsed feed: normalised country name → level.
#
# A dict rather than a list of (title, level) tuples because the lookup we
# actually want is by name, and building the dict forces us to answer "what is
# the country name in this title?" once, at parse time, instead of dodging the
# question with a substring test at every lookup.
_by_country: Optional[dict[str, int]] = None
_fetched_at: float = 0.0      # wall clock (time.time) — survives restarts
_failed_at: float = 0.0       # monotonic — process-local by design
_disk_checked: bool = False

# Observed title forms, both real in the live feed:
#     "Mexico Travel Advisory - Level 2: Exercise Increased Caution"
#     "Democratic Republic of the Congo - Level 4: Do Not Travel"
# The separator is sometimes an en/em dash. Some entries are regional rather
# than national ("Mexico - Sinaloa State - Level 4"); those keep their
# qualifier in the name and won't match a bare country name, which is correct.
_TITLE_RE = re.compile(
    r"^\s*(?P<name>.+?)\s*[-–—]\s*Level\s*(?P<level>[1-4])\b",
    re.IGNORECASE,
)

# Some titles carry this suffix and some don't, so it is noise in the name, not
# part of it. Stripping it is what lets the exact match do the work: without it
# "Mexico" only resolved via the word-boundary fallback, and "Guinea" would
# have been at the mercy of dict ordering against "Papua New Guinea".
_TITLE_SUFFIX_RE = re.compile(r"\s+travel\s+advisor(y|ies)$")

# Names the model says vs. names the feed uses. Only two survive contact with
# the real feed: it already spells South Korea, Vietnam, Russia and Myanmar the
# way a person would, so aliases for those were solving a problem that doesn't
# exist. Add an entry only when you have watched a name go unresolved.
_ALIASES: dict[str, str] = {
    "uk": "united kingdom",
    "czech republic": "czechia",
}


# ── Name handling ────────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    """
    Casefold, strip accents and punctuation, collapse whitespace, drop the
    'Travel Advisory' suffix and a leading 'the'.

    'Côte d'Ivoire' and "Cote d Ivoire" should be the same key. This is not
    fuzzy matching — it removes representation differences only, never
    meaning. 'Niger' and 'Nigeria' stay distinct, which is the entire point.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = ascii_only.casefold()
    cleaned = re.sub(r"[^a-z0-9,\s]", " ", lowered)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _TITLE_SUFFIX_RE.sub("", cleaned)
    if cleaned.startswith("the "):
        cleaned = cleaned[4:]
    return cleaned


def _level_from_entry(entry: dict[str, Any], title: str) -> Optional[int]:
    """
    Prefer an explicit numeric level field if the feed offers one; fall back to
    parsing it out of the title.

    The live feed has no such field today — every entry carries Title, Link,
    Category and Summary — so the title parse is the real path. The field
    lookup is cheap insurance for the day the feed tidies its titles.
    """
    for key in ("Level", "AdvisoryLevel", "level"):
        raw = entry.get(key)
        if raw is None:
            continue
        m = re.search(r"[1-4]", str(raw))
        if m:
            return int(m.group())

    m = _TITLE_RE.match(title)
    return int(m.group("level")) if m else None


def _name_from_title(title: str) -> Optional[str]:
    """'Mexico Travel Advisory - Level 2: Exercise Increased Caution' → 'mexico'"""
    m = _TITLE_RE.match(title)
    if not m:
        return None
    return _normalize(m.group("name"))


def _parse_feed(raw: Any) -> dict[str, int]:
    """
    Feed document → {normalised country name: level}.

    Raises on an unexpected shape OR an empty array. Called from inside
    _refresh's try block, so either is recorded as a refresh failure — backoff
    applies and the previous copy, if any, keeps serving.
    """
    if not isinstance(raw, list):
        raise ValueError(
            f"Expected a JSON array of advisories, got {type(raw).__name__}"
        )

    if not raw:
        # 200 OK, two bytes. The endpoint does this erratically. It is NOT a
        # statement that no advisories exist anywhere in the world.
        raise ValueError(
            "Feed returned an empty array — the endpoint does this erratically. "
            "Treating as a failure, not as data."
        )

    parsed: dict[str, int] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(
                f"Expected advisory objects, got {type(entry).__name__}"
            )
        title = entry.get("Title") or entry.get("title") or ""
        if not title:
            continue
        name = _name_from_title(title)
        level = _level_from_entry(entry, title)
        if name and level is not None:
            # First title wins. The feed lists the national advisory before its
            # regional supplements, and a national name parsed out of a
            # regional title would be a different key anyway.
            parsed.setdefault(name, level)

    if not parsed:
        raise ValueError(
            f"Feed returned {len(raw)} entries but none parsed — the title "
            f"format has probably changed"
        )
    return parsed


# ── Disk cache ───────────────────────────────────────────────────────────────

def _load_from_disk() -> None:
    """
    Populate the in-memory map from the cache file, if it exists and parses.

    Deliberately forgiving: a missing, truncated, or garbage cache file is a
    cache miss, not an error. The only thing that must never happen is a
    corrupt file producing a plausible-looking wrong advisory, which is why the
    shape is validated rather than trusted.
    """
    global _by_country, _fetched_at

    try:
        payload = json.loads(_CACHE_PATH.read_text())
        levels = payload["levels"]
        fetched_at = float(payload["fetched_at"])
        if not isinstance(levels, dict) or not levels:
            raise ValueError("empty or malformed 'levels'")
        parsed = {str(k): int(v) for k, v in levels.items()}
    except FileNotFoundError:
        return
    except Exception as e:
        logger.warning(f"Ignoring unreadable advisory cache at {_CACHE_PATH}: {e}")
        return

    _by_country = parsed
    _fetched_at = fetched_at
    age_h = max(0.0, (time.time() - fetched_at) / 3600)
    logger.info(
        f"Advisory cache loaded from disk — {len(parsed)} advisories, "
        f"{age_h:.1f}h old"
    )


def _save_to_disk() -> None:
    """
    Write the parsed map atomically. Never raises: failing to cache is not
    failing to answer.
    """
    if _by_country is None:
        return
    try:
        payload = {"fetched_at": _fetched_at, "levels": _by_country}
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, _CACHE_PATH)  # atomic — no half-written cache
    except Exception as e:
        logger.warning(f"Could not write advisory cache to {_CACHE_PATH}: {e}")


# ── Refresh ──────────────────────────────────────────────────────────────────

def _refresh() -> None:
    """Fetch and parse the feed. Leaves previous data intact on failure."""
    global _by_country, _fetched_at, _failed_at

    try:
        resp = httpx.get(_FEED_URL, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        parsed = _parse_feed(resp.json())
    except Exception as e:
        _failed_at = time.monotonic()
        if _by_country is None:
            logger.warning(f"Advisory feed unavailable and no cached copy: {e}")
        else:
            age_h = max(0.0, (time.time() - _fetched_at) / 3600)
            logger.warning(
                f"Advisory feed refresh failed ({e}) — serving cached copy "
                f"({age_h:.1f}h old)"
            )
        return

    _by_country = parsed
    _fetched_at = time.time()
    _failed_at = 0.0
    logger.info(f"Advisory feed refreshed — {len(parsed)} country advisories")
    _save_to_disk()


def _ensure_fresh() -> None:
    global _disk_checked

    if not _disk_checked:
        # Once per process. A miss here is normal on a cold machine.
        _disk_checked = True
        if _by_country is None:
            _load_from_disk()

    if _by_country is not None and time.time() - _fetched_at < _TTL_S:
        return  # cache is good

    if _failed_at and time.monotonic() - _failed_at < _FAILURE_BACKOFF_S:
        return  # recently failed; don't hammer it (this is what stopped the 429 loop)

    _refresh()


# ── Lookup ───────────────────────────────────────────────────────────────────

def _lookup_level(country: str) -> Optional[int]:
    """
    Normalised name → level, or None.

    Three passes, narrowest first:
      1. exact normalised name   — 'Guinea' finds Guinea, not Papua New Guinea
      2. known alias             — 'UK' → the feed's own spelling
      3. word-boundary scan      — reaches regional or qualified titles, but
                                   'Oman' does NOT find 'Romania'

    There is no fourth pass, and pass 3 refuses to choose between two hits. A
    bare substring test is how Mali got Somalia's Level 4.
    """
    if _by_country is None:
        return None

    key = _normalize(country)

    level = _by_country.get(key)
    if level is not None:
        return level

    alias = _ALIASES.get(key)
    if alias:
        level = _by_country.get(_normalize(alias))
        if level is not None:
            return level

    pattern = re.compile(rf"\b{re.escape(key)}\b")
    hits = [(name, lvl) for name, lvl in _by_country.items() if pattern.search(name)]

    if len(hits) == 1:
        name, lvl = hits[0]
        logger.debug(f"Advisory for '{country}' matched feed entry '{name}'")
        return lvl

    if len(hits) > 1:
        # Never pick one. Whichever we returned would be dict-order roulette on
        # a safety claim, and the neutral placeholder is the honest answer.
        logger.warning(
            f"Advisory for '{country}' is ambiguous — matched "
            f"{[n for n, _ in hits]}. Returning no advisory rather than guessing."
        )

    return None


def advisory_note(country: str) -> Optional[str]:
    """
    Short advisory note for a country, or None if unknown/unavailable.

    None means "we don't know" — callers must NOT substitute a guess.
    """
    if not country:
        return None

    _ensure_fresh()
    if not _by_country:
        return None

    level = _lookup_level(country)
    if level is None:
        # Worth a line: a country the model proposes but the feed doesn't name
        # under that spelling is an alias candidate, and the only way to find
        # one is to see it go unresolved.
        logger.info(f"No advisory entry matched country '{country}'")
        return None

    return ADVISORY_NOTES.get(level)