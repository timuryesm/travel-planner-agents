# Rebuild plan — hub-and-spoke redesign

Status: proposed. Supersedes the multi-city model in `docs/trip_state_model.md`.

---

## 1. The model, restated

One country. One hub city. Optional day-trips out and back.

```
        Toronto
           │  roundtrip flight (01/10 → 16/10)
           ▼
   ┌───► Tokyo ◄───┐        ← hub: accommodation for the whole stay
   │       │       │
   ▼       ▼       ▼
 Kyoto   Osaka   Nara       ← spokes: dates chosen within the trip window,
 (05/10) (08/10) (11/10)      travel out and back the same trip, no hotel
```

Consequences that fall out of this, and why the old design's problems disappear:

- **No flight chain.** One roundtrip, origin ↔ hub. The current `FlightAgent` already does exactly this.
- **No per-stop accommodation.** One hotel, hub, whole period. The current `HotelAgent` already does exactly this.
- **No "which city do I fly home from."** Always the hub.
- **Spoke cities need dates**, chosen by the user inside the trip window, constrained to `> departure_date` and `< return_date`.

Scoped out for now: staying overnight in a spoke city. If the user wants that, the agent gives a text suggestion about where to stay there, with no accommodation API call.

---

## 2. Stage sequence

```
setup → country → city → flights → [intercity] → accommodation
      → activities[0] → activities[1] → … → daily_plan → final
```

`[intercity]` appears only when more than one city was committed.

**Trip-level:** setup, country, city, flights, intercity, accommodation, daily_plan, final
**Stop-level:** activities — and *only* activities

That's the significant structural change: the stop block shrinks from four stages to one. `flights`, `accommodation`, and `daily_plan` all become trip-level because there is exactly one of each per trip now.

### Why `position.py` barely changes

`flattened_sequence()` is built from three lists in `enums.py`. Rewriting those lists rewrites the sequence. The one real edit is making `intercity` conditional:

```python
def flattened_sequence(num_stops: int) -> list[Position]:
    sequence = []
    for stage in TRIP_PRE_STOP_STAGES:
        # Intercity travel only exists when there's somewhere to travel to.
        # num_stops is the signal, so this stays a pure function of num_stops.
        if stage is TripLevelStage.intercity and num_stops < 2:
            continue
        sequence.append(Position(stage=stage.value))
    ...
```

The "single place that encodes stage ordering" discipline from Phase B is what makes this cheap. It's paying off exactly as intended.

### Sequences by stop count

```
0 stops (before city commit):
  setup, country, city, flights, accommodation, daily_plan, final

1 stop:
  setup, country, city, flights, accommodation, activities[0], daily_plan, final

3 stops:
  setup, country, city, flights, intercity, accommodation,
  activities[0], activities[1], activities[2], daily_plan, final
```

`transition()` already rebuilds the sequence after the destination commit changes stop count — same hook, renamed to `city`.

---

## 3. Editing / blast radius

No new machinery needed. This already works:

- **Edit any stage** → `BACK` → `_invalidate_after()` resets everything downstream to unvisited, everything upstream is untouched. That is exactly the "previous steps lost, earlier steps kept" behaviour requested.
- **Edit activities from daily_plan** → `BACK(activities, i)` → daily_plan is invalidated, but the activities commit *is the target*, not downstream of it, so it survives. `ActivitiesStage` restores selections from `commitData`. Already the pattern `AccommodationStage` uses.

The only thing to verify is that the blast-radius modal's copy still makes sense with the new stage names.

---

## 4. Reconciliation

Recommend **dropping it**. Its job was nagging about skipped stop-level stages; with only `activities` at stop level and a flow that goes activities → daily_plan → final, there is close to nothing left for it to say.

If dropped: remove from `TRIP_POST_STOP_STAGES`, delete `ReconciliationStage.jsx`, and `TripStatus.reconciling` loses its trigger.

---

## 5. File inventory

### Delete

| File | Why |
|---|---|
| `frontend/src/components/wizard/DestinationStage.jsx` | Split into CountryStage + CityStage |
| `frontend/src/components/wizard/ReconciliationStage.jsx` | Stage dropped (pending confirmation) |

### Rename (`git mv`, so history follows)

| From | To |
|---|---|
| `src/agents/destination_agent.py` | `src/agents/country_agent.py` |

### New — backend

| File | Purpose |
|---|---|
| `src/agents/city_agent.py` | Proposes cities within the chosen country |
| `src/agents/intercity_agent.py` | Hub → spoke travel options, web search + citations |
| `src/api/routes/assemble.py` | `POST /trips/{id}/assemble` |

### New — frontend (mind the casing on every one of these)

| File |
|---|
| `frontend/src/components/wizard/CountryStage.jsx` |
| `frontend/src/components/wizard/CityStage.jsx` |
| `frontend/src/components/wizard/IntercityStage.jsx` |

### Rewrite

| File | Change |
|---|---|
| `src/state/enums.py` | New stage lists — the load-bearing edit |
| `src/state/position.py` | `intercity` conditional on `num_stops >= 2` |
| `src/state/transition.py` | `destination` → `city` hook; intercity commit writes stop dates |
| `src/state/schemas.py` | New commit payloads (below) |
| `src/state/travel_plan.py` | `Country`, `City`, `IntercityOption`; multi-value agent results |
| `src/db/models.py` | `Stop.start_date`, `Stop.end_date` |
| `src/db/trip_repository.py` | `create_trip` seeds new trip-level stages; `create_stops` takes dates |
| `src/agents/options_adapter.py` | New fetchers; hints (preference, exclude) |
| `src/api/routes/stage_options.py` | Request body for hints; `run_in_threadpool` |
| `src/agents/activities_agent.py` | Preference text, regenerate, expand, 10 suggestions |
| `src/agents/budget_agent.py` | `aggregate()` entry point incl. intercity costs |
| `src/agents/orchestrator.py` | `assemble_from_wizard()` — render committed days, don't re-derive |
| `frontend/src/api/client.js` | Hints in body; cache key includes them |
| `frontend/src/components/wizard/SetupStage.jsx` | Remove multi-city toggle |
| `frontend/src/components/wizard/ActivitiesStage.jsx` | Preference line, regenerate, expand, selection list w/ reorder |
| `frontend/src/components/wizard/DailyPlanStage.jsx` | Real weather, Edit → activities |
| `frontend/src/components/wizard/FinalStage.jsx` | Actually a final stage this time |
| `frontend/src/components/wizard/WizardRenderer.jsx` | New stage map |
| `frontend/src/components/wizard/stages.jsx` | New barrel |
| `frontend/src/components/layout/Sidebar.jsx` | New stage groups |
| `frontend/src/i18n/*` | New keys × 3 languages |

### Migration

One new Alembic revision: `stops.start_date`, `stops.end_date`, both nullable dates.

Nullable is honest here — it means "the intercity stage hasn't been reached yet," not "guess from the trip." The hub stop (index 0) gets the setup dates at creation; spokes stay NULL until the intercity commit fills them.

`multi_city` stays on `trips` as a denorm, but is now set at the **city** commit from `len(cities) > 1` rather than asked at setup.

---

## 6. Commit payloads

```python
class SetupCommitData(BaseModel):
    origin: str
    departure_date: date
    return_date: date
    num_travelers: int
    travel_type: Literal["relax", "active", "hybrid"]
    budget_amount: Optional[float]
    budget_currency: str = "USD"
    with_kids: bool = False
    preferences_text: Optional[str] = None
    # multi_city removed — derived from the city commit

class CountryCommitData(BaseModel):
    country: Country          # name, why_chosen_summary, climate_note, safety_note

class CityCommitData(BaseModel):
    cities: list[City] = Field(min_length=1)   # ordered; [0] is the hub

class FlightsCommitData(BaseModel):
    selected: FlightOption    # unchanged — roundtrip origin ↔ hub

class IntercityCommitData(BaseModel):
    segments: list[IntercitySegment]
    # segment: stop_index, city, travel_date, return_date, selected: IntercityOption

class AccommodationCommitData(BaseModel):
    selected: HotelOption
    check_in: date
    check_out: date           # new — user picks, defaults to return_date

class ActivitiesCommitData(BaseModel):
    chosen: list[Activity]    # ordered — the user can reorder
    preference_text: Optional[str] = None

class DailyPlanCommitData(BaseModel):
    day_by_day: list[DayPlan]

class FinalCommitData(BaseModel):
    itinerary_markdown: str
    budget: BudgetBreakdown
    generated_at: datetime
```

Deleted: `DestinationCommitData`.

---

## 7. Options endpoint gains a body

Regenerate, expand, and the activities preference line all need to reach the agent. The route's own docstring anticipated this:

> POST also leaves room to pass stage-specific hints in the body later without reworking the signature.

That time is now:

```python
class StageOptionsRequest(BaseModel):
    stop_index: Optional[int] = None
    preference_text: Optional[str] = None
    exclude: list[str] = []      # names already shown — powers regenerate/expand
    limit: Optional[int] = None
```

`client.js`'s cache key must include the hints, or a regenerate returns the cached list. Simplest: keep the key as `(trip, stage, stop)` and pass `{force: true}` whenever hints are present.

---

## 8. Steps

Each numbered step is one commit. Push after each.

### Track 1 — single city, end to end

The wizard currently has **no ending**. Everything in Track 1 is aimed at getting one city all the way to a rendered itinerary. At the end of Track 1 the project is demonstrable; today it is not.

| # | Step | Notes |
|---|---|---|
| 1 | Wipe the 4 test trips; `run_in_threadpool` in `stage_options.py` | One line, unblocks everything with a Claude call in it |
| 2 | `enums.py` + `position.py` + tests | Pure Python, no DB. The foundation |
| 3 | Alembic migration: `stops.start_date`, `stops.end_date` | Schema only — data was wiped in step 1 |
| 4 | `trip_repository.py`: new trip-level stages, stops with dates | |
| 5 | `schemas.py` + `travel_plan.py`: new payloads and models | Delete `DestinationCommitData` |
| 6 | `transition.py`: `city` commit hook | Rebuilds sequence, creates stops, sets `multi_city` |
| 7 | `git mv destination_agent.py country_agent.py`; climate note; regenerate support | Advisory lookup lands where it belongs — advisories *are* country-level |
| 8 | `city_agent.py` + fetcher | |
| 9 | Frontend: `SetupStage` (drop multi-city), `CountryStage`, `CityStage` (Proceed only) | Delete `DestinationStage.jsx` |
| 10 | `activities_agent.py`: preference, regenerate, expand, 10 | |
| 11 | `ActivitiesStage.jsx` rewrite: preference line, regenerate, selection list w/ reorder | |
| 12 | Weather → `STAGE_FETCHERS`; `DailyPlanStage` rewrite | Delete `MOCK_WEATHER`. Real Open-Meteo forecast |
| 13 | `budget_agent.aggregate()` | Shared by CLI `run()` and the wizard |
| 14 | `POST /trips/{id}/assemble` + `orchestrator.assemble_from_wizard()` | The big one |
| 15 | `FinalStage.jsx` — real | Renders, regenerates, commits |

**→ Single-city works end to end.** Portfolio-viable from here.

### Track 2 — multi-city

| # | Step |
|---|---|
| 16 | `CityStage`: "Add another city", reorder/remove list |
| 17 | `intercity_agent.py` — web search + citations |
| 18 | `IntercityStage.jsx` — date pickers (constrained), agent options |
| 19 | Activities loop across stops; assembly renders spokes |

### Track 3 — Plans and sharing

| # | Step |
|---|---|
| 20 | "Plans" section — trip list + resume (retires the auto-create placeholder) |
| 21 | Download the plan |
| 22 | Google Calendar export |
| 23 | Share (confirm-before-send) |

### Track 4 — deployment

| # | Step |
|---|---|
| 24 | PNG → WebP |
| 25 | Deploy |

---

## 9. Assembly, specifically

Step 14 is the largest and the most worth doing well. Design:

**It does not persist.** `POST /trips/{id}/assemble` reads committed state, aggregates the budget, calls Claude, returns `{itinerary_markdown, budget}`. `FinalStage` renders it, offers regenerate, and commits it through the normal `transition()` COMMIT path.

That keeps the single-chokepoint rule: assembly *generates*, `transition()` *persists*. Revisiting `final` reads `commitData` instead of paying for a regeneration.

**It does not fit `STAGE_FETCHERS`.** Those take `(setup, city)` and return a list of options. Assembly takes the whole trip and returns one object. Forcing it in would bend the adapter the way the assembly prompt is currently bent.

**The prompt must change.** The Phase A prompt says:

> distribute the activities sensibly across the available days, accounting for the weather each day

But by then `daily_plan` is committed. The user saw those days, possibly edited them, and pressed confirm. Re-deriving would silently override their plan — and editing that plan is the whole point of Track 3. The wizard prompt renders the committed days; it does not re-plan them.

Likewise `_build_context` labels activities `AVAILABLE ACTIVITIES (N options)`. In the wizard they are the chosen ones.

---

## 10. Known risks

- **`assemble_itinerary` is a 4096-token synchronous Claude call.** 20–40s on the event loop freezes the whole server. Step 1 (`run_in_threadpool`) is a prerequisite, not a nicety.
- **`safe_run()` masks failures as empty results.** It already hid one bug this week. Worth revisiting before the surface area grows.
- **Web search costs real money per call.** Cache intercity results per `(hub, spoke, date)` the way `advisory_lookup` caches the feed, or a regenerate button becomes a billing surprise.
- **i18n triples every string.** EN/FR/RU × ~6 new stages. Easy to defer and painful to retrofit.