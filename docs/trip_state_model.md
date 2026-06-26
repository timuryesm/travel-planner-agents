# Trip State Model — Design Spec

**Status:** Design artifact (Phase B seed). No code yet.
**Scope:** The stateful, resumable, stepwise wizard that replaces the old single-shot pipeline.
**Decisions locked in this spec are v1.** Where a decision is deliberately reversible later, it's marked **[reversible]**.

---

## 1. Overview

The app is a wizard: at each stage the AI proposes options, the user inspects/refines in a loop, then commits. The committed choice feeds the next stage. The same pattern repeats at every stage (destination, flights, hotels, activities, daily plan), so it is built **once** and reused.

The heart of the system is this state model — not the orchestrator and not the UI. Free backward navigation, forward navigation, skipping, and final-plan assembly all fall out of getting this model right.

---

## 2. Stage sequence

The navigable sequence is **flattened and ordered**, and is **generated from the destination commit** (because the number of cities isn't known until then).

**Single-city:**

```
setup → destination → flights → accommodation → activities → daily_plan → reconciliation → final
```

**Multi-city** (per-stop block repeats once per chosen city):

```
setup → destination
  → [flights·1 → accom·1 → activities·1 → plan·1]
  → [flights·2 → accom·2 → activities·2 → plan·2]
  → … 
  → reconciliation → final
```

- **Trip-level stages** (outside the per-stop loop): `setup`, `destination`, `reconciliation`, `final`.
- **Stop-level stages** (inside the loop, tagged with a stop index): `flights`, `accommodation`, `activities`, `daily_plan`.
- A **position** is a pointer into this flattened sequence: either a trip-level stage or a stop-level stage + stop index.

**Consequence:** downstream navigation never needs to know whether the trip is single- or multi-city. Pick one city → the per-stop block appears once; pick three → it appears three times. One navigation logic serves both.

---

## 3. Stage commit wrapper

Every **stop-level** stage wraps its data in a uniform structure, so the transition function can treat all stages identically:

| Field | Meaning |
|---|---|
| `commit_type` | One of `chosen` \| `self_provided` \| `skipped` \| `unvisited` |
| `commit_data` | Stage-specific payload (nullable — null when skipped/unvisited) |
| `self_provided_text` | Free-text; populated only when `commit_type == self_provided` |
| `completed` | bool. `chosen`, `self_provided`, `skipped` → true; `unvisited` → false |

The `completed` flag is what distinguishes a **deliberate skip** (completed) from a **genuine gap** (unvisited) — even though both have null `commit_data`.

### Commit types

- **chosen** — user picked an option from AI/API results.
- **self_provided** — user wrote their own (e.g. "I've booked Air Canada AC061, $1,180"). Not an API result; user's own data slotted into the same shape. AI incorporates it into the final plan.
- **skipped** — user pressed the skip button deliberately. Respected, not an error.
- **unvisited** — never reached, or passed through with FORWARD without choosing.

---

## 4. Per-stage commit data (the `chosen` payload)

| Stage | Level | `commit_data` (when chosen) | Notes |
|---|---|---|---|
| **setup** | trip | `{ dates (interval), num_travelers, travel_type (relax\|active\|hybrid), budget_amount?, budget_currency (default USD), with_kids, preferences_text?, multi_city }` | The seed input. Expanded `TravelRequest`. |
| **destination** | trip | single city `{ city, country, why_chosen_summary, season_note, safety_note }`, OR ordered list of these if `multi_city` | If `multi_city` unchecked → exactly 1 city. Checked → 1..N cities. |
| **flights** | stop | `{ selected: FlightOption }` | Existing `FlightOption` model. Cheapest/comfortable/fastest are ranking labels over the options list; commit is the one chosen option. |
| **accommodation** | stop | `{ selected: HotelOption }` | Existing `HotelOption`; its `provider` field already distinguishes booking.com vs airbnb. One slot regardless of column. |
| **activities** | stop | `{ chosen: list[Activity] }` | Existing `Activity`. Commit is a **list**, unlike flights/hotels. |
| **daily_plan** | stop | `{ day_by_day: list[DayPlan] }` | New model needed. Generated from chosen activities + dates, then **mutated by free-text chat edits**. Stored form = current edited version. |

**New models to add:** `Destination`, `DayPlan` (date, weather line, ordered activity references). Existing models (`FlightOption`, `FlightLeg`, `HotelOption`, `Activity`) carry over unchanged.

---

## 5. Navigation — the transition function

All navigation routes through **one** entry point: `transition(trip, action)`. Nothing mutates position anywhere else. This single-chokepoint discipline is what keeps future changes (a forward gate, smart-invalidation) a one-place edit.

### Actions

```
transition(trip, action):
    case COMMIT(type, data):        # type ∈ {chosen, self_provided}
        cur.commit_type = type
        cur.commit_data = data
        cur.completed   = True
        advance(trip)

    case SKIP:
        cur.commit_type = skipped
        cur.commit_data = None
        cur.completed   = True
        advance(trip)

    case FORWARD:                   # no pick, no skip
        advance(trip)               # current stays unvisited

    case BACK(target):
        invalidate_after(trip, target)   # cascade
        trip.current = target
```

### advance() — the only loop-seam-aware function

```
advance(trip):
    if cur is a stop's LAST stage and more stops remain:
        go to next stop's FIRST stage
    elif cur is the final stop's last stage:
        go to reconciliation
    else:
        go to next stage (+1)
```

- **Forward is +1, one stage at a time. No forward-jump** in v1.
- All multi-stage movement is backward (`BACK(target)`) or the reconciliation "add now" jump-back.

---

## 6. Cascade-invalidate (option 1)

Editing any upstream stage clears all downstream commits; the user re-walks forward.

```
invalidate_after(trip, target):
    for every stage AFTER target in the sequence:
        commit_type = unvisited
        commit_data = None
        completed   = False
```

- **Blast-radius warning** shown *before* executing a BACK move is computed from the **same set**: every stage after `target` that is `completed` (or holds data). Same set, two uses — name it, then clear it.
- The warning names the real blast radius (e.g. jumping from daily-plan back to destination loses flights, hotels, activities, **and** the plan) — not just "this step."

### Two largest-blast-radius edits

- **Back to `setup`** — invalidates everything downstream, including re-running destination discovery.
- **Back to `destination`, changing city count** — does more than reset: it **regenerates the sequence** (3 stops → 2 changes the flattened list's length). Destination is the one stage whose edit can *restructure* navigation, not merely reset it.

> **[reversible]** v1 uses cascade-invalidate (option 1). The model stores enough (per-stage commit + completed) that smart-invalidation (option 2) can be added later without a rewrite. Decision deferred until after project completion.

---

## 7. Cross-stop dependency — same-airline preference

For multi-city, flights should use the same airline across stops where possible (Part 2, step 8).

- This is a **stage concern, not a transition concern.** When the flight stage for stop k≥2 generates proposals, *that stage* reads stop k−1's committed carrier and biases toward it.
- Deliberately kept **out of** `transition()`. Transition is about navigation; stages are about content. Keeping cross-stop logic out of the navigator preserves the clean single-chokepoint property.
- The loop structure (stop-major) makes this natural: by the time stop k's flight stage runs, stop k−1 is already committed.

---

## 8. Reconciliation (pre-final gate)

Before assembly, scan for stages needing attention and offer three doors each:

1. **Add it now** → jump back to that stage (backward nav; at pre-final there's nothing downstream to lose).
2. **Write my own** → free-text capture → becomes a `self_provided` commit.
3. **Skip for good** → stays out of the plan.

Then AI assembles: incorporate `chosen` + `self_provided`, omit `skipped`.

### Which stages get nagged — policy seam

```
reconciliation_targets(trip):
    policy = NAG_BOTH          # v1 default
    for stage in stop_stages:
        if policy == NAG_BOTH      and stage.commit_type in {skipped, unvisited}:
            yield stage
        if policy == NAG_GAPS_ONLY and stage.commit_type == unvisited:
            yield stage
```

> **[reversible]** v1 = `NAG_BOTH`. Rationale: nagging both is the safer error — nagging a deliberate skip costs one extra click (mildly annoying); failing to nag a genuine gap costs a silently incomplete plan. Flip to `NAG_GAPS_ONLY` later by changing one constant. The model supports either for free because `completed` already separates skipped from unvisited.

> **Note:** reconciliation is the **one exception** to "no forward gates." Forward navigation is otherwise unrestricted; this is a single checkpoint at the finish line, only for missing stages.

---

## 9. What changes vs. the current engine

**Survives essentially intact:**
- All six agents (weather, flight, hotel, Airbnb, activities, budget) keep their core fetch/parse logic.
- Append-to-shared-state pattern.
- Mock fallbacks.
- Final assembly (weather + flights + hotels + per-day activities + budget → one document).

**Changes structurally:**
- Orchestration flips from run-all-at-once to a **stepwise state machine** that pauses at each stage.
- **Persistence becomes a hard dependency** (Phase B Postgres + JWT) — wizard state must survive between requests.
- **Two new AI capabilities:** destination discovery (with a **live travel-advisory safety signal — must not come from model memory**), and travel-type-aware generation (relax/active/hybrid + kids).

---

## 10. Open design notes (for later, not blocking)

- **Refine-loop quota policy:** strongly lean **fetch-larger-set-once, then filter/re-rank in memory**; only re-call live APIs when something changes that genuinely requires it (new dates, new city). Critical given free-tier limits (Skyscanner hit 93%, Airbnb 100%).
- **Currency:** store user's chosen currency in setup, pass through to every API call so budget math needs no conversion.
- **Daily-plan free-text editing:** define what AI may change vs. what's locked.
- **Email sharing + Google Calendar (step 10):** integrations with their own auth; Phase D/E scope; nothing in core flow blocks on them. Email send = confirm-before-send action.
- **Soft limits** on unbounded refine loops (destination "more options", activities "more").

---

## 11. Next artifact

Translate this model into the **persistence schema** — tables/columns for a `Trip`, its `Stop`s, and each stage's commit wrapper. Mostly mechanical translation of sections 3–4.