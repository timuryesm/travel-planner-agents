# Schema design notes

**Artifact:** Phase B persistence schema  
**Translates:** `docs/trip_state_model.md` sections 3–4  
**Status:** v1 locked

---

## Two stage-commit tables, not one

The obvious first instinct is a single `stage_commits` table with a nullable `stop_id`. That works, but it loses the DB's ability to enforce that every stop-level commit belongs to a stop. A nullable FK means "this row might reference stops, or might not" — you can't add `NOT NULL` and you can't write a meaningful check constraint across both branches.

Two tables costs nothing at query time (the application always knows which table it's on — it knows whether the current stage is trip-level or stop-level) and buys clean `NOT NULL` FKs on both sides:

- `trip_stage_commits.trip_id` → `trips.id` NOT NULL  
- `stop_stage_commits.stop_id` → `stops.id` NOT NULL

---

## JSONB for commit_data, not one table per stage

Each stage has a different payload shape:

| Stage | commit_data schema |
|---|---|
| `setup` | `SetupCommitData` |
| `destination` | `DestinationCommitData` |
| `flights` | `FlightsCommitData` |
| `accommodation` | `AccommodationCommitData` |
| `activities` | `ActivitiesCommitData` |
| `daily_plan` | `DailyPlanCommitData` |

Fully normalising those into six separate tables would mean 6-way JOINs just to load a single trip. JSONB is the right call here because:

1. The Pydantic schemas in `src/state/schemas.py` are the schema registry — validation happens at the application boundary on every read and write.
2. Payload shapes are stable within a major version and tracked in code.
3. Loading a trip is a small number of rows (`4 trip-level + 4×stops stop-level`) — no N+1 risk.

The trade-off is that Postgres can't validate JSONB contents beyond "it's valid JSON." That's accepted: Pydantic fills the gap.

---

## `completed` is stored, not derived

The spec says:

> `completed` == True for chosen, self_provided, skipped  
> `completed` == False for unvisited

You could derive this from `commit_type`. We store it anyway because:

- **Reconciliation query** becomes `WHERE completed = FALSE` — one column scan, no CASE expression.
- **NAG_BOTH vs NAG_GAPS_ONLY** policy switch maps cleanly: NAG_BOTH uses `completed = FALSE`, NAG_GAPS_ONLY uses `commit_type = 'unvisited'`. Both are O(index scan), neither needs expression evaluation.
- The partial index `ix_stop_stage_commits_incomplete` (WHERE completed = false) makes the reconciliation scan fast regardless of trip size.

---

## `multi_city` denormalised on `trips`

`Trip.multi_city` mirrors `setup_commit.commit_data["multi_city"]`. It's written when the setup commit is saved and updated if the user goes back to setup.

Without this column, listing a user's trips (e.g. "all your in-progress trips") requires extracting a field from a JSONB column to answer "is this a multi-city trip?" — not a big deal for 10 trips, but bad practice and harder to index.

---

## Two-part wizard position (`current_stage` + `current_stop_index`)

A single JSONB position object would also work. Two columns are simpler to:
- Query: `WHERE current_stage = 'flights' AND current_stop_index = 1`
- Index: straightforward column index if needed
- Debug: readable in `psql` without JSON extraction

`current_stop_index` is `NULL` for all trip-level stages (setup, destination, reconciliation, final). A non-null value always means we're inside the per-stop block.

---

## String columns for enum values, not Postgres ENUM types

All enum-like columns (`status`, `stage`, `commit_type`) use `VARCHAR(32)` with CHECK constraints, not native Postgres ENUM types.

Why: adding a value to a Postgres ENUM requires `ALTER TYPE` with a table rewrite. `VARCHAR` + CHECK lets us add a new commit type or stage by updating the CHECK constraint in a migration without touching rows.

The Python enum classes (`CommitType`, `TripLevelStage`, `StopLevelStage`) enforce valid values at the application layer. The CHECK constraints are a belt-and-suspenders catch for any code path that bypasses the ORM.

---

## Stop rows are created lazily

Stop rows don't exist until the destination commit is written. There's no reason to pre-allocate them — we don't know the city count until the user commits. When the destination commit lands:

1. Parse `DestinationCommitData.destinations` (a list).
2. Create one `Stop` row per city.
3. Create four `StopStageCommit` rows per stop (all `unvisited`).

When the user goes **back to destination** and commits a different set of cities, the cascade-invalidate path deletes the old Stop rows (and their StopStageCommits, via `ON DELETE CASCADE`) and runs step 1–3 again. This is the only structural mutation — all other cascade-invalidate operations just reset commit columns in place.

---

## `updated_at` is ORM-managed, not trigger-managed

SQLAlchemy's `onupdate=` hook fires for ORM-driven updates (`session.add`). Bulk UPDATE statements (used by `invalidate_after` to reset many rows at once) must set `updated_at = now()` explicitly.

This is a v1 trade-off. A Postgres trigger can enforce `updated_at` for all update paths later. The current approach avoids trigger complexity in the initial migration.

---

## The spec's `[reversible]` markers and what they mean for the schema

Both reversible decisions in the spec are expressible with what's already in the schema:

- **Cascade-invalidate → smart-invalidate** (`[reversible]` section 6): no schema change needed. Smart-invalidation would inspect individual commit states before clearing — the data is already there.
- **NAG_BOTH → NAG_GAPS_ONLY** (`[reversible]` section 8): query parameter change only. `WHERE completed = FALSE` vs `WHERE commit_type = 'unvisited'`. Both work against the current schema with no migration.

---

## New Python files introduced

| File | Purpose |
|---|---|
| `src/state/enums.py` | `CommitType`, `TripLevelStage`, `StopLevelStage`, `TripStatus` + navigation helpers |
| `src/state/schemas.py` | Pydantic commit_data payload schemas; re-exports `FlightOption`, `HotelOption`, `Activity` |
| `src/db/base.py` | Async engine, session factory, `Base`, `get_db` FastAPI dependency |
| `src/db/models.py` | `User`, `Trip`, `Stop`, `TripStageCommit`, `StopStageCommit` ORM models |
| `alembic/env.py` | Alembic config (strips asyncpg → psycopg2 for migration connections) |
| `alembic/versions/0001_initial_schema.py` | Initial migration — creates all five tables |

`src/state/travel_plan.py` is **unchanged.**