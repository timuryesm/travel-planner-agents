"""
Plan edit route — free-text edits to the daily plan.

    POST /trips/{trip_id}/plan-edit

Stateless with respect to the plan. The daily plan is local to the wizard
until the user presses Confirm (same as the manual ↑/↓ moves), so the
component sends its working copy and gets OPERATIONS back. Nothing is
persisted here; the commit still happens through transition().

Why ops rather than a rewritten plan: see PlanEditAgent's docstring. The
short version is that ops fail individually and a rewritten plan fails
totally.

The split of validation:

  here          each op names an activity that is actually on this trip.
                The route can check that — it has the activities commits.
                An op naming something the user never chose is dropped with
                a reason, not applied.

  the component the structural rules: same-city moves only, valid dates,
                ordering. Those live in DailyPlanStage's applier, which is
                the same tested code the manual move buttons use. Putting a
                second copy in Python would let the two drift, and only one
                of them would ever be exercised.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.plan_edit_agent import PlanEditAgent
from src.auth.jwt import get_current_user
from src.db.base import get_db
from src.db.models import Trip, User
from src.db.trip_repository import load_trip
from src.state.enums import StopLevelStage
from src.state.schemas import ActivitiesCommitData, DayPlan

router = APIRouter(prefix="/trips", tags=["plan-edit"])

MAX_MESSAGE_CHARS = 500


class PlanEditRequest(BaseModel):
    """
    The working plan plus what the user typed.

    day_by_day is validated as real DayPlan objects rather than taken as raw
    dicts: the agent is about to be shown these dates and city labels, and a
    malformed day would produce confidently wrong ops.
    """
    day_by_day: list[DayPlan] = Field(min_length=1)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class PlanEditOp(BaseModel):
    op: Literal["move", "remove"]
    activity: str
    to_date: Optional[str] = None
    position: Literal["start", "end"] = "end"


class PlanEditResponse(BaseModel):
    ops: list[PlanEditOp]
    note: str
    # Ops the agent proposed that name an activity not on this trip. Surfaced
    # rather than silently dropped — a user who asked for something and got
    # nothing deserves to know which part was not understood.
    rejected: list[dict[str, Any]] = Field(default_factory=list)


@router.post(
    "/{trip_id}/plan-edit",
    response_model=PlanEditResponse,
    summary="Interpret a free-text edit to the daily plan as operations",
)
async def plan_edit(
    trip_id: uuid.UUID,
    body: PlanEditRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlanEditResponse:
    trip = await load_trip(trip_id, db)
    if trip is None or trip.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found.",
        )

    known = _committed_activity_names(trip)
    if not known:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No activities have been chosen yet, so there is nothing to rearrange.",
        )

    agent = PlanEditAgent(
        day_by_day=[d.model_dump(mode="json") for d in body.day_by_day],
        message=body.message,
    )
    try:
        result = await run_in_threadpool(agent.generate_ops)
    except Exception as e:
        # Upstream (Claude) failed, or the response could not be parsed. 502,
        # matching the assemble route: this service is fine, the model call
        # is not, and a retry is a reasonable response.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not interpret that edit. Please try rephrasing.",
        ) from e

    accepted: list[PlanEditOp] = []
    rejected: list[dict[str, Any]] = []

    # Case-insensitive match, then snap to the canonical spelling: the agent
    # is told to copy names exactly, and mostly does, but a difference of case
    # should not lose a legitimate edit. The stored name wins so the op
    # matches the plan's own strings.
    canonical = {name.casefold(): name for name in known}

    for raw in result["ops"]:
        try:
            op = PlanEditOp.model_validate(raw)
        except Exception:
            rejected.append({"op": raw, "reason": "malformed"})
            continue

        match = canonical.get(op.activity.casefold())
        if match is None:
            rejected.append({"op": raw, "reason": "unknown_activity"})
            continue
        op.activity = match

        if op.op == "move" and not op.to_date:
            rejected.append({"op": raw, "reason": "missing_date"})
            continue

        accepted.append(op)

    return PlanEditResponse(
        ops=accepted,
        note=result["note"],
        rejected=rejected,
    )


def _committed_activity_names(trip: Trip) -> set[str]:
    """
    Every activity the user actually chose, across the hub and every spoke.

    Same gathering order as assembly.build_plan_from_commits — one source of
    truth for "what is on this trip".
    """
    names: set[str] = set()
    for stop in trip.stops:
        commit = next(
            (
                c
                for c in stop.stop_stage_commits
                if c.stage == StopLevelStage.activities.value
            ),
            None,
        )
        if commit is None or not commit.completed or not commit.commit_data:
            continue
        chosen = ActivitiesCommitData.model_validate(commit.commit_data).chosen or []
        names.update(a.name for a in chosen)
    return names