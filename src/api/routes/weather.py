"""
Weather route — real forecast for the daily-plan stage.

    GET /trips/{trip_id}/weather

Returns a per-day forecast for the hub city across the trip window, plus a flag
saying whether it's a live forecast or a seasonal proxy.

Why this isn't in STAGE_FETCHERS
--------------------------------
Every stage-options fetcher returns a LIST of things the user picks from.
Weather is neither a list nor a choice — it's one object of context laid over
the days the daily-plan stage generates. Forcing it through the options adapter
would bend that adapter the way the old assembly prompt was bent. So weather
gets its own read-only endpoint, and DailyPlanStage overlays the result onto
the plan it builds client-side.

WeatherAgent already does the hard part: geocode the city, pick the live
forecast when the trip is within ~15 days, otherwise last year's same dates as
a seasonal proxy labelled "(typical)". This route just runs it against the hub
and reshapes WeatherSummary.forecast_by_day into a date→line map the component
can look up.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.weather_agent import WeatherAgent
from src.auth.jwt import get_current_user
from src.db.base import get_db
from src.db.models import User
from src.db.trip_repository import load_trip
from src.state.schemas import SetupCommitData
from src.state.enums import TripLevelStage
from src.state.travel_plan import TravelPlan, TravelRequest

router = APIRouter(prefix="/trips", tags=["weather"])


class WeatherResponse(BaseModel):
    city: str
    # date (ISO "YYYY-MM-DD") → human line, e.g. "Partly cloudy, 15-24C" or
    # "(typical) Rain, 12-18C". The component keys into this by DayPlan.date.
    forecast_by_day: dict[str, str]
    packing_tips: list[str]
    # True when the lines are a seasonal proxy from last year rather than a live
    # forecast — the trip is too far out for a real one. The UI says so.
    is_seasonal: bool


@router.get(
    "/{trip_id}/weather",
    response_model=WeatherResponse,
    summary="Per-day forecast for the hub city across the trip window",
)
async def get_weather(
    trip_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WeatherResponse:
    trip = await load_trip(trip_id, db)
    if trip is None or trip.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found.",
        )

    setup_commit = next(
        (c for c in trip.trip_stage_commits if c.stage == TripLevelStage.setup.value),
        None,
    )
    if not setup_commit or not setup_commit.commit_data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup must be completed before requesting weather.",
        )
    setup = SetupCommitData.model_validate(setup_commit.commit_data)

    hub = next((s for s in trip.stops if s.stop_index == 0), None)
    if hub is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A city must be chosen before requesting weather.",
        )

    req = TravelRequest(
        origin=setup.origin,
        destination=hub.city,
        departure_date=setup.departure_date,
        return_date=setup.return_date,
        budget_usd=float(setup.budget_amount or 0) or 3000.0,
        travelers=setup.num_travelers,
        trip_type="roundtrip",
        with_kids=setup.with_kids,
        travel_style=setup.travel_type,
        preferences_text=setup.preferences_text,
        language=setup.language,
    )

    plan = TravelPlan(request=req)
    # Geocoding + HTTP are blocking; keep them off the event loop. safe_run so a
    # weather failure degrades to an empty forecast (the component falls back to
    # a neutral line) rather than 500-ing the whole daily-plan stage.
    plan = await run_in_threadpool(WeatherAgent().safe_run, plan)

    if plan.weather is None:
        # Agent failed — safe_run logged the traceback. Empty forecast; the
        # component shows a neutral note rather than breaking.
        return WeatherResponse(
            city=hub.city, forecast_by_day={}, packing_tips=[], is_seasonal=False
        )

    # WeatherAgent tags proxy lines with a leading "(typical) " and prepends a
    # matching packing tip. Read the flag off that tip rather than re-deriving
    # the date arithmetic here — one source of truth for "is this real".
    tips = plan.weather.packing_tips
    is_seasonal = any("historical data" in tip for tip in tips)

    forecast = plan.weather.forecast_by_day

    if is_seasonal:
        # The proxy is keyed by LAST YEAR's dates (the archive the agent hit),
        # but the daily-plan component builds its days in the trip year, so a
        # lookup by trip date would miss every day. Shift the keys forward onto
        # the actual trip window by ordinal position: the agent fetched the same
        # calendar span a year back, so day-by-day the ordering lines up. This
        # is why the forecast rendered blank before — the data was right, the
        # keys were a year off.
        trip_dates = [
            (setup.departure_date + timedelta(days=i)).isoformat()
            for i in range((setup.return_date - setup.departure_date).days + 1)
        ]
        proxy_lines = list(forecast.values())  # dict preserves insertion order
        forecast = {
            trip_dates[i]: proxy_lines[i]
            for i in range(min(len(trip_dates), len(proxy_lines)))
        }

    return WeatherResponse(
        city=hub.city,
        forecast_by_day=forecast,
        packing_tips=tips,
        is_seasonal=is_seasonal,
    )