"""
Pure renderer: the confirmed final commit -> a downloadable markdown document.

The itinerary is NOT re-derived here. FinalCommitData.itinerary_markdown is
what the user saw and pressed Confirm on; the download must be that document
verbatim, not a fresh serialization that could disagree with it. This module
only wraps it: a header of trip facts the itinerary doesn't carry (route,
dates, party), the advisory as recorded at commit time, and a provenance
footer.

No ORM, no FastAPI, no I/O — the endpoint feeds it validated commit payloads.
Same shape as BudgetAgent.aggregate(): callable from the wizard route today,
the Phase D email sender tomorrow, a CLI whenever.

Money and budget are deliberately absent: the itinerary's own budget section
was generated from the same BudgetBreakdown stored in the commit (assemble.py
passes it into the assembly context for exactly that reason), so a second
table here would duplicate it.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Optional

from src.state.schemas import (
    CityCommitData,
    CountryCommitData,
    FinalCommitData,
    SetupCommitData,
)


def export_filename(country: str, hub_city: str, departure_date: date) -> str:
    """
    "Japan", "Tokyo", 2026-10-01 -> "japan-tokyo-2026-10-01.md"

    ASCII-slugged because this crosses a Content-Disposition header and every
    OS's filename rules; the document itself stays fully Unicode.
    """
    def slug(s: str) -> str:
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
        s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
        return s or "trip"

    return f"{slug(country)}-{slug(hub_city)}-{departure_date.isoformat()}.md"


def render_export_markdown(
    *,
    final: FinalCommitData,
    setup: SetupCommitData,
    country: CountryCommitData,
    cities: CityCommitData,
    advisory_as_of: Optional[date] = None,
) -> str:
    """
    advisory_as_of: the country commit's creation date. The safety note was
    fetched live from the State Dept feed when the country was committed; the
    export labels it with that date rather than refetching, because the
    itinerary below it is equally frozen at generated_at — a today-fresh
    advisory stapled to a weeks-old plan would imply a currency the document
    doesn't have. Advisory text stays English regardless of app language
    (it is quoted from the feed, not authored).
    """
    hub = cities.cities[0].city
    city_names = [c.city for c in cities.cities]
    out: list[str] = []

    # ── Header: the facts the itinerary body doesn't restate ─────────────
    out.append(f"# {country.country.name} — {' · '.join(city_names)}")
    out.append("")
    traveler_word = "traveler" if setup.num_travelers == 1 else "travelers"
    facts = [
        f"**{setup.origin} → {hub}**",
        f"{setup.departure_date.isoformat()} → {setup.return_date.isoformat()}",
        f"{setup.num_travelers} {traveler_word}",
    ]
    if setup.budget_amount is not None:
        facts.append(f"budget {setup.budget_amount:,.0f} {setup.budget_currency}")
    out.append(" · ".join(facts))
    out.append("")

    if country.country.safety_note:
        as_of = f", as of {advisory_as_of.isoformat()}" if advisory_as_of else ""
        out.append(
            f"> **Travel advisory (U.S. State Department{as_of}):** "
            + country.country.safety_note
        )
        out.append("")

    out.append("---")
    out.append("")

    # ── The confirmed itinerary, verbatim ────────────────────────────────
    out.append(final.itinerary_markdown.strip())
    out.append("")

    # ── Provenance footer ────────────────────────────────────────────────
    out.append("---")
    out.append("")
    out.append(
        f"_Generated {final.generated_at.date().isoformat()} "
        f"by travel-planner-agents._"
    )

    return "\n".join(out) + "\n"