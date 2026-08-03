"""
Export route — download the confirmed plan as a markdown document.

    GET /trips/{trip_id}/export

Serves what was CONFIRMED, verbatim. The final commit's itinerary_markdown is
the document the user pressed Confirm on; this route wraps it (header facts,
dated advisory, provenance footer) and never re-derives it — a regenerated
plan that hasn't been confirmed is deliberately not what you download.

Thin by design: commit reading lives in assembly.export_inputs_from_commits
(assembly is the one place that reads commit rows), rendering lives in
state.plan_export (pure). This route does auth, HTTP, and headers.

409 when there is no final commit — an unconfirmed trip has nothing truthful
to serve, and half a document would be worse than none.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.assembly import AssemblyNotReady, export_inputs_from_commits
from src.auth.jwt import get_current_user
from src.db.base import get_db
from src.db.models import User
from src.db.trip_repository import load_trip
from src.state.plan_export import (
    export_filename,
    render_export_markdown,
    render_export_pdf,
)

router = APIRouter(prefix="/trips", tags=["export"])


@router.get(
    "/{trip_id}/export",
    summary="Download the confirmed plan as a markdown document",
)
async def export_plan(
    trip_id: uuid.UUID,
    format: Literal["md", "pdf"] = Query("md", description="Document format"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    trip = await load_trip(trip_id, db)
    if trip is None or trip.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found.",
        )

    try:
        inputs = export_inputs_from_commits(trip)
    except AssemblyNotReady as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e

    document = render_export_markdown(**inputs)
    filename = export_filename(
        inputs["country"].country.name,
        inputs["cities"].cities[0].city,
        inputs["setup"].departure_date,
    )

    if format == "pdf":
        # PDF generation is CPU-bound (~1s: font parsing dominates). Off the
        # event loop, same reasoning as the assemble route's Claude call.
        content = await run_in_threadpool(render_export_pdf, document)
        media_type = "application/pdf"
        filename = filename.removesuffix(".md") + ".pdf"
    else:
        content = document
        media_type = "text/markdown; charset=utf-8"

    # filename is ASCII-slugged by export_filename, so the plain filename=
    # form is header-safe; the body itself is full UTF-8 (RU/FR ready).
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )