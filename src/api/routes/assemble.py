"""
Assemble route — generate the final itinerary from committed choices.

    POST /trips/{trip_id}/assemble

Generate-only, on purpose. It reads the commits, writes the itinerary and the
budget, and RETURNS them — it persists nothing. The user commits the result
through the normal transition path, which stores it as the `final` commit.

Why two steps rather than assembling straight into the commit:

The itinerary is a DERIVED artifact — a function of every upstream choice. The
moment it's stored, "is it still current?" becomes a question. Keeping it in
the `final` commit means transition()'s existing cascade-invalidate answers
that for free: go BACK and change the hotel, and the final commit is
invalidated like any other downstream stage. Assemble-and-persist here would
put the itinerary outside the commit system, where the cascade can't reach it,
and staleness would have to be tracked by hand.

It also keeps the expensive part explicit. Assembly is a 4k-token Claude call;
making it a deliberate endpoint the user triggers (and can re-trigger via
Regenerate) means it runs on demand, not inside every FORWARD.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.assembly import (
    AssemblyNotReady,
    build_plan_from_commits,
    generated_at,
    wizard_costs_from_commits,
)
from src.agents.budget_agent import BudgetAgent
from src.agents.orchestrator import Orchestrator
from src.auth.jwt import get_current_user
from src.db.base import get_db
from src.db.models import User
from src.db.trip_repository import load_trip
from src.state.travel_plan import BudgetBreakdown

router = APIRouter(prefix="/trips", tags=["assembly"])


class AssembleResponse(BaseModel):
    # Exactly FinalCommitData's shape, so the frontend can hand this straight
    # back as the commit payload with no reshaping.
    itinerary_markdown: str
    budget: BudgetBreakdown
    generated_at: str


@router.post(
    "/{trip_id}/assemble",
    response_model=AssembleResponse,
    summary="Generate the final itinerary from the trip's committed choices",
)
async def assemble(
    trip_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AssembleResponse:
    trip = await load_trip(trip_id, db)
    if trip is None or trip.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found.",
        )

    try:
        plan = build_plan_from_commits(trip)
        costs = wizard_costs_from_commits(trip)
    except AssemblyNotReady as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e

    # Budget first — cheap, deterministic, and it goes into the assembly context
    # so the itinerary's budget section matches the number we return.
    budget: BudgetBreakdown = BudgetAgent.aggregate(**costs)
    plan.budget = budget

    # Then the expensive Claude call, off the event loop. If it fails, surface a
    # 502 the component can retry rather than a 500 — the upstream (Claude) is
    # what failed, not this service.
    try:
        itinerary = await run_in_threadpool(Orchestrator().assemble_itinerary, plan)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate the itinerary. Please try again.",
        ) from e

    if not itinerary or not itinerary.strip():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The itinerary came back empty. Please try again.",
        )

    return AssembleResponse(
        itinerary_markdown=itinerary,
        budget=budget,
        generated_at=generated_at().isoformat(),
    )