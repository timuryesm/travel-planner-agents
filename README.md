# Travel Planner Agents

A multi-agent AI travel-planning application with a stepwise wizard UI,
persistent state, and JWT authentication. Specialized agents handle each
planning domain — country, city, flights, intercity travel, hotels, weather,
activities, and budget — coordinated by a wizard state machine that lets users
navigate, skip, and revise each stage of their plan.

Built as a portfolio project targeting production-readiness: clean
architecture, resumable sessions, real external APIs, and a multilingual React
frontend (English / French / Russian).

> **Status:** complete and deployed. A trip can be planned from setup through a
> rendered itinerary, across one city or several, saved, resumed, edited, and
> downloaded as Markdown or PDF. Remaining work is polish — see the roadmap.
> The commit history is the source of truth for what's done.

**Live demo:** https://travel-planner-agents-production.up.railway.app

Registration is gated by an invite code, because every trip spends real
Anthropic credits. Ask if you'd like one.

---

## The model: hub-and-spoke

One country. One hub city you fly a roundtrip to. Optional day-trips out to
nearby "spoke" cities and back the same day — no second hotel, no second flight.

```
        Toronto
           │  roundtrip flight
           ▼
   ┌───► Tokyo ◄───┐        ← hub: the one hotel, for the whole stay
   │       │       │
   ▼       ▼       ▼
 Kyoto   Osaka   Nara       ← spokes: day-trips out and back, dates chosen
                              inside the trip window; no accommodation
```

This replaced an earlier design that searched a separate roundtrip from the
origin to *every* city — which asked questions with no good answer ("which city
do you fly home from?") and multiplied flights and hotels a traveler didn't
want. Hub-and-spoke makes the common case ("base yourself somewhere, take a few
day-trips") the natural one:

- **One flight** — origin ↔ hub, roundtrip.
- **One hotel** — in the hub, for the whole period.
- **One daily plan** — spanning the trip, moving between hub and spokes.
- **Activities repeat per city** — the only thing that does.

Staying overnight in a spoke is out of scope: the agent can suggest where you'd
stay, but books nothing.

---

## Wizard stage sequence

```
setup → country → city → flights → [intercity] → accommodation
      → activities[0..N] → daily_plan → final
```

- **Trip-level** (one per trip): setup, country, city, flights, intercity,
  accommodation, daily_plan, final.
- **Stop-level** (one per city): activities — and only activities.
- **`intercity`** appears only when more than one city is committed; single-city
  trips skip it entirely.

The sequence is derived from three lists in `enums.py` by
`flattened_sequence(num_stops)`, so the whole ordering — including whether
`intercity` exists — is one edit in one place. Committing the city list is what
restructures navigation: it creates the Stop rows and rebuilds the sequence.

---

## Architecture

The frontend never talks to an agent directly. Stages that need *proposed
options* before the user can choose fetch them from one endpoint that runs the
matching agent against committed wizard state:

```
   Wizard stage mounts
          │
          │  POST /trips/{id}/stages/{stage}/options   (hints in the body)
          ▼
   ┌──────────────────┐
   │  stage_options   │  ← validates stage, checks ownership, reads the
   │     (route)      │    setup + country + stop commits; 409s if a
   └────────┬─────────┘    prerequisite stage isn't done yet
            │  run_in_threadpool  (agents are synchronous)
            ▼
   ┌──────────────────┐
   │ options_adapter  │  ← builds a synthetic TravelPlan from commit
   │                  │    state; passes stage hints to the agent
   └────────┬─────────┘
            │  safe_run()
            ▼
   ┌──────────────────────────────────────────────────────┐
   │ Country │ City │ Flight │ Intercity │ Hotel │ Activities │
   └────────┬─────────────────────────────────────────────┘
            │
            ▼
    options[] shaped for that stage's commit payload
```

The adapter exists because the agents are built around a single-shot
`TravelPlan`, while the wizard's state is spread across commit rows. One
translation layer bridges them, so the same agents serve both the CLI pipeline
and the stepwise UI without either being rewritten for the other.

Three endpoints sit outside that flow because they aren't option lists:

- **`GET /trips/{id}/weather`** — one object of context, not a list of choices.
- **`POST /trips/{id}/assemble`** — generates the final itinerary from every
  committed choice, and returns it *without persisting*.
- **`POST /trips/{id}/plan-edit`** — interprets a free-text edit to the daily
  plan as structured operations, and persists nothing.

Navigation and persistence go through a single function — `transition(trip,
action)` — which handles COMMIT / SKIP / FORWARD / BACK, validates each commit
payload against its stage's schema *before* writing, and cascade-invalidates
downstream stages on a backward jump.

### Commit reading has one home

`agents/assembly.py` is the only module that reads commit rows. Assembly,
budget aggregation, and export all go through it, so the ORM never leaks into
an agent and "what did the user actually choose" has a single implementation.

---

## Agents

| Agent | Data source | On failure |
|---|---|---|
| **Country** | Claude + U.S. State Dept advisory feed | Curated country pool |
| **City** | Claude (within the committed country) | Raises — no honest generic answer |
| **Weather** | Open-Meteo forecast / archive API | Empty forecast, neutral note |
| **Flights** | Skyscanner via RapidAPI | Realistic mock data |
| **Intercity** | Claude + web search (with citations) | Raises |
| **Hotels** | Booking.com via RapidAPI | Realistic mock data |
| **Airbnb** | Airbnb19 via RapidAPI | Realistic mock data |
| **Activities** | Claude | Curated activity pool |
| **Plan edit** | Claude | Raises — no generic answer to "what did they mean" |
| **Budget** | Aggregates all agent results | — |
| **Orchestrator** | Claude — assembles the final itinerary | — |

Country and city notes are deliberately split by source:

- **climate_note** comes from the model — the *typical* climate for the dates,
  which is stable knowledge, not a forecast. There's no forecast to be had at
  country/city selection: Open-Meteo needs coordinates, and the real forecast
  arrives at the daily-plan stage, which has both a city and dates.
- **safety_note** comes from the live State Department advisory feed, never the
  model. Advisories change, and stale or invented safety guidance is worse than
  none. On a lookup miss the note is dropped, not guessed.

Intercity travel has no booking API behind it — there's no endpoint for "trains
from Tokyo to Kyoto and what they cost" — so it comes from Claude with web
search. That makes the numbers indicative rather than quotes, and the
`Citation` list that produced them reaches the UI rather than being dropped.

### Key design decisions

**Shared state over direct agent communication.** Agents never call each other.
They read from and write to a single `TravelPlan` Pydantic object, which keeps
them independently testable and swappable.

**Single transition chokepoint.** All wizard navigation and persistence go
through `transition(trip, action)`. Commit-payload validation, forward gates,
and cascade-invalidate are all one-place edits. Assembly *generates* but does
not persist; `transition()` persists.

**Validate on write, at the boundary.** Each stage's commit payload is stored as
JSONB and validated against a typed Pydantic schema *before* it's written —
`_COMMIT_SCHEMAS` maps every stage to its schema. A bad payload is rejected with
a 422 and the trip is untouched, rather than persisting and surfacing as a 500
several stages downstream.

**Grounded parsing over hope.** Every Claude-backed agent asks for JSON through
one shared helper (`BaseAgent.ask_claude_json`) that parses defensively — strips
a stray markdown fence, falls back to the outermost object, retries once on a
transient failure, and never retries a deterministic 4xx. Before it existed, a
model that wrapped its reply in backticks would drop an agent silently into its
fallback.

**Honest failure over cheerful emptiness.** `safe_run()` catches any agent
crash and logs the traceback — but the discovery stages (country, city) turn a
failure into a 502 the UI can retry, rather than a 200 with an empty list that
reads as "nothing found." Stages with a real fallback (flights, hotels,
activities) degrade to it instead.

**Mock-first development.** Every agent with an external API dependency has a
realistic mock fallback, and the flag-off mock path is the *same* code that runs
on an API failure — so leaving the flags off exercises the real degradation
path, not a special test mode.

**Live signals over model memory.** Safety notes come from the current State
Department feed, cached with a TTL, never from the LLM.

**One definition per shape.** `Country`, `City`, and the agent-result models are
declared once in `travel_plan.py` and re-exported from `schemas.py`, so an
agent's output and the matching commit payload validate against the same class
and cannot drift.

**The confirmed plan is the artifact.** Export serves the itinerary the user
pressed Confirm on, verbatim, rather than re-deriving a document from commits.
Two renderings of the same trip that disagree would be worse than one plain
one. PDF is a second renderer over the same Markdown, so the formats cannot
drift apart.

**Edits are operations, not rewrites.** A free-text edit ("move the museum to
Thursday") returns a list of ops, not a rewritten plan. A hallucinated activity
name fails one op and is reported; a rewritten plan would fail silently and
totally. The structural rules — a spoke day's activities can't move to a hub
day — are enforced in code, not by trusting the model to have read the
instruction.

---

## Agent JSON, weather, and advisories — the tricky bits

Five subsystems earned dedicated handling; each is documented at its source.

- **`tools/advisory_lookup.py`** — caches the State Dept feed (one document
  covering every country) on disk with a 6-hour TTL, matches countries by exact
  name rather than substring (so "Niger" never picks up "Nigeria"'s level),
  treats the feed's occasional empty `[]` response as a failure rather than
  data, and refuses to guess when a name is ambiguous.
- **`agents/weather_agent.py`** — geocodes the hub, uses a live forecast when
  the trip is within ~15 days, otherwise last year's same dates as a seasonal
  proxy (labelled *typical*). The route re-keys the proxy onto the trip's actual
  dates so the daily plan can look weather up by date.
- **`tools/geocode_lookup.py`** — caches Nominatim results on disk with no
  TTL (coordinates don't change), spaces requests to respect the one-per-second
  policy, and never caches a failure — a rate-limit block and "no such place"
  are indistinguishable in the response, so a negative cache would poison a
  city permanently.
- **`agents/base_agent.py`** — `ask_claude_json` and `safe_run`, described
  above.
- **`state/plan_export.py`** — wraps the confirmed itinerary for download.
  Table cells are flattened before PDF rendering because `fpdf2`'s `write_html`
  raises on mixed content inside a `<td>`, which real itineraries hit via
  booking links.

---

## Project structure

```
travel-planner-agents/
├── src/
│   ├── agents/
│   │   ├── base_agent.py        ← shared contract + ask_claude_json + safe_run
│   │   ├── orchestrator.py      ← Claude-powered final assembly
│   │   ├── assembly.py          ← commit rows → TravelPlan / budget / export inputs
│   │   ├── country_agent.py     ← Claude + live travel advisories
│   │   ├── city_agent.py        ← Claude, cities within the chosen country
│   │   ├── weather_agent.py     ← Open-Meteo forecast / seasonal proxy
│   │   ├── flight_agent.py      ← Skyscanner search (roundtrip origin↔hub)
│   │   ├── intercity_agent.py   ← hub↔spoke travel, Claude + web search
│   │   ├── hotel_agent.py       ← Booking.com + property type filter
│   │   ├── airbnb_agent.py      ← Airbnb listings + combined results
│   │   ├── activities_agent.py  ← Claude; preference / regenerate / expand
│   │   ├── plan_edit_agent.py   ← free-text daily-plan edits → operations
│   │   ├── budget_agent.py      ← aggregates all agent results
│   │   └── options_adapter.py   ← wizard commit state → TravelPlan agents
│   ├── api/
│   │   └── routes/
│   │       ├── auth.py          ← register / login
│   │       ├── trips.py         ← create / list / get / delete / transition
│   │       ├── stage_options.py ← runs an agent for one wizard stage
│   │       ├── weather.py       ← per-day forecast for the hub
│   │       ├── assemble.py      ← generate the final itinerary (no persist)
│   │       ├── export.py        ← download the confirmed plan (md / pdf)
│   │       └── plan_edit.py     ← interpret a free-text plan edit as ops
│   ├── auth/
│   │   └── jwt.py               ← token creation + get_current_user
│   ├── state/
│   │   ├── travel_plan.py       ← Pydantic models for agent data
│   │   ├── enums.py             ← CommitType, stage enums, TripStatus
│   │   ├── position.py          ← Position + flattened_sequence()
│   │   ├── transition.py        ← COMMIT/SKIP/FORWARD/BACK + validation
│   │   ├── schemas.py           ← commit_data payload schemas per stage
│   │   └── plan_export.py       ← confirmed plan → Markdown / PDF (pure)
│   ├── db/
│   │   ├── base.py              ← async engine, session factory, get_db
│   │   ├── models.py            ← User, Trip, Stop, TripStageCommit, StopStageCommit
│   │   └── trip_repository.py   ← async DB layer (create_trip, load_trip, …)
│   ├── tools/
│   │   ├── airport_lookup.py    ← IATA code lookup (API + fallback table)
│   │   ├── advisory_lookup.py   ← cached State Dept advisory feed
│   │   └── geocode_lookup.py    ← cached, rate-limited Nominatim geocoding
│   ├── config/
│   │   ├── settings.py          ← environment variable loader + feature flags
│   │   └── logging_config.py    ← reclaims root logger after Alembic's fileConfig
│   ├── assets/fonts/            ← vendored DejaVu faces (PDF export, Cyrillic)
│   └── main.py                  ← FastAPI entrypoint (lifespan, CORS, routers)
├── frontend/
│   ├── src/
│   │   ├── api/client.js        ← single gateway to the backend
│   │   ├── store/tripStore.js   ← Zustand; backend is authoritative
│   │   ├── hooks/               ← useTorontoTheme (day/night by timezone)
│   │   ├── components/
│   │   │   ├── auth/            ← AuthScreen
│   │   │   ├── background/      ← TorontoSkyline, AnimatedElements
│   │   │   ├── layout/          ← AppShell, Sidebar
│   │   │   ├── plans/           ← TripListScreen (resume, multi-select delete)
│   │   │   └── wizard/          ← WizardRenderer + one component per stage
│   │   └── i18n/                ← EN / FR / RU translations
│   └── package.json
├── alembic/versions/           ← schema migrations
├── scripts/                    ← one-off asset tooling
├── docs/
│   ├── rebuild_plan.md         ← the hub-and-spoke redesign plan (25 steps)
│   ├── trip_state_model.md     ← original wizard design spec
│   └── schema_design_notes.md  ← schema decisions explained
├── tests/                      ← agent unit tests, mocked APIs
├── main.py                     ← CLI entry point
└── requirements.txt
```

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/register` | Create account, returns JWT |
| `POST` | `/auth/login` | Form-encoded login, returns JWT |
| `POST` | `/trips/` | Create trip + one unvisited commit per trip-level stage |
| `GET` | `/trips/` | List the caller's trips |
| `GET` | `/trips/{id}` | Full trip state (position, commits, stops) |
| `DELETE` | `/trips/{id}` | Delete a trip; cascades to stops and commits |
| `POST` | `/trips/{id}/transition` | COMMIT / SKIP / FORWARD / BACK |
| `POST` | `/trips/{id}/stages/{stage}/options` | Run the stage's agent, return options |
| `GET` | `/trips/{id}/weather` | Per-day forecast for the hub city |
| `POST` | `/trips/{id}/assemble` | Generate the final itinerary (returns, doesn't save) |
| `POST` | `/trips/{id}/plan-edit` | Interpret a free-text daily-plan edit as operations |
| `GET` | `/trips/{id}/export?format=md\|pdf` | Download the confirmed plan |
| `GET` | `/health` | Liveness check |

Interactive docs at `/docs` (Swagger, with an Authorize button) and `/redoc`.

Trips are scoped to their owner: another user's trip returns 404, not 403 — the
API doesn't confirm the existence of resources you can't see.

---

## Database schema

Five tables in PostgreSQL. All PKs are UUIDs. Cascade-delete on all FKs.

```
users
  └── trips  (current_stage, current_stop_index, multi_city)
        ├── trip_stage_commits  (setup | country | city | flights |
        │                        intercity | accommodation | daily_plan | final)
        └── stops  (stop_index, city, country, start_date, end_date)
              └── stop_stage_commits  (activities)
```

`multi_city` is derived at the **city** commit from `len(cities) > 1`, not asked
at setup. Stop dates are nullable — the hub (index 0) takes the trip dates at
creation; spokes stay NULL until the intercity stage fills them. Each commit row
carries `commit_type` (chosen / self_provided / skipped / unvisited),
`commit_data` (JSONB, validated by a Pydantic schema on write),
`self_provided_text`, and `completed`.

Commit rows are pre-created as `unvisited` when the trip is created, so
`updated_at` — not `created_at` — is when a stage was actually committed.

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/timuryesm/travel-planner-agents.git
cd travel-planner-agents
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Start Postgres

```bash
docker run -d \
  --name travel-planner-db \
  -e POSTGRES_USER=travel \
  -e POSTGRES_PASSWORD=travel \
  -e POSTGRES_DB=travel_planner \
  -p 5432:5432 \
  postgres:16
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Fill in:

```
ANTHROPIC_API_KEY=sk-ant-...        # console.anthropic.com
RAPIDAPI_KEY=...                    # rapidapi.com (one key for all APIs below)
DATABASE_URL=postgresql+asyncpg://travel:travel@localhost:5432/travel_planner
SECRET_KEY=...                      # any long random string for JWT signing
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

`DATABASE_URL` and `SECRET_KEY` are read at import time and have no defaults — a
missing value fails fast at startup rather than connecting somewhere unintended.

**Feature flags** (in `src/config/settings.py`, both default to `False`):

| Flag | Effect when `False` |
|---|---|
| `SKYSCANNER_ENABLED` | Flight agent returns mock data through the real code path |
| `AIRBNB_ENABLED` | Hotel agent returns mock data through the real code path |

The RapidAPI free tiers have small quotas a development loop exhausts quickly.
The mock paths are the same code that runs on an API failure, so leaving the
flags off exercises the real degradation path.

### 4. Run database migrations

Migrations also run on app startup, so this is only needed for the CLI or a
fresh database inspected before first boot.

```bash
alembic upgrade head
```

### 5. Run the backend

```bash
uvicorn src.main:app --reload
```

### 6. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server runs on `http://localhost:5173` and reads its API base URL from
`VITE_API_BASE_URL` (default `http://localhost:8000`), so no frontend `.env` is
needed for local development.

### 7. Run the CLI (optional)

```bash
python main.py
```

---

## PDF export and fonts

`fpdf2` ships no fonts, so the DejaVu Sans faces used by the PDF renderer are
vendored in `src/assets/fonts/` (with their license). The alternative — an
`apt`/`brew` install plus path discovery — differs between a developer's laptop
and a container, and the failure mode is a runtime `FileNotFoundError` rather
than a build error.

DejaVu covers Latin *and* Cyrillic, so a Russian-language plan will render
correctly once agent output is localised.

Both `fpdf2` and `markdown` are pure Python; the deployment image needs no
system packages for PDF generation.

---

## Deployment

One image serves both the API and the built frontend. The alternative —
separate backend and nginx containers — buys faster partial rebuilds and costs
a second Dockerfile, an nginx config, live CORS in production, and two things
to keep in sync. Sharing an origin also removes cross-origin entirely once
deployed: `ALLOWED_ORIGINS` matters only against the Vite dev server.

Run the deployed shape locally:

```bash
docker compose up --build
open http://localhost:8000
```

That is for verifying a build, not for developing — `uvicorn --reload` and
`npm run dev` remain the development loop, and a container rebuild is only
needed when deploying a change.

The compose Postgres publishes no host port, so it doesn't collide with a
development database already on 5432. In production only the app container is
deployed; the platform provides managed Postgres.

**Environment variables in a deployed environment** — the same names as `.env`,
set in the platform's dashboard rather than a file:

| Variable | Notes |
|---|---|
| `DATABASE_URL` | On Railway, the reference `${{Postgres.DATABASE_URL}}` rather than a pasted string, so it re-resolves if the database is recreated |
| `SECRET_KEY` | Generate a fresh one; it signs JWTs |
| `ANTHROPIC_API_KEY` | Required |
| `RAPIDAPI_KEY` | Optional — the mock paths run without it |
| `INVITE_CODE` | **Set this.** Empty means open registration |
| `SKYSCANNER_ENABLED` / `BOOKING_ENABLED` / `AIRBNB_ENABLED` | Default `False` |

Managed providers hand out `postgresql://` with no driver named;
`src/db/base.py` normalises it to `postgresql+asyncpg://` in code rather than
requiring a hand-edited URL, which would break the reference above.

Migrations run in the FastAPI lifespan, so a deploy needs no separate step —
but it also means a database that isn't reachable stops the container rather
than degrading.

**Cost note.** The app spends real Anthropic credits per trip: a country agent,
a city agent, activities per city, and a ~4k-token assembly call, each
repeatable via Regenerate. `INVITE_CODE` plus a spend limit on the Anthropic
console are what stand between a public URL and an open wallet.

---

## Tests

```bash
python -m pytest tests/ -v
```

Agents have unit tests with mocked external calls. A `conftest.py` fixture
clears the API keys, so tests run without internet, without keys, and without
spending quota — fast, free, deterministic.

---

## Known limitations

Honest notes on what isn't finished, kept here rather than in a private list.

- **`safe_run()` still flattens some failures.** Discovery stages now surface a
  502, but flights / hotels / activities still degrade to an empty (or fallback)
  list, so a genuine failure there is only visible in the server log, not the
  response.
- **Geocoding is unkeyed.** Results are now cached on disk and rate-limited,
  which removes the self-inflicted request volume, but Nominatim still has no
  API key and no quota guarantee. A public deployment wants a keyed geocoder.
- **Mock flight estimates only know Toronto routes.** `_estimate_route` has a
  table of Toronto-prefixed long- and medium-haul routes; everything else gets
  a 550 USD / 9-hour default, which is roughly double reality for a Caribbean
  flight and feeds straight into the budget.
- **Mock flights share one booking link.** The URL is built from cities and
  dates, so every option points at the same search. A per-option link to the
  actual itinerary requires Skyscanner's own `bookingUrl`, which exists only
  on the flag-on path.
- **Cities outside the code tables get no deep link.** Skyscanner deep links
  need a city code; for an unknown city the booking URL degrades to the
  Skyscanner homepage rather than guessing a code and pointing at the wrong
  route.
- **Airbnb is unreachable from the wizard.** `options_adapter` never calls
  `AirbnbAgent`, so `AIRBNB_ENABLED` currently changes nothing. The agent
  works and is tested; it has no route into the UI.
- **Caches are ephemeral in a container.** The advisory and geocode caches
  live under the system temp directory, so a redeploy or a restarted replica
  starts cold. Correct but wasteful; a mounted volume would fix it.
- **Degrading fetchers ignore `plan.errors`.** Flights, accommodation,
  activities and intercity correctly degrade to a fallback rather than 502 —
  but an agent that recorded an error and produced nothing logs nothing at the
  adapter level, which is how an aborted flights stage went unnoticed.
- **A trip straddling the forecast horizon loses its live forecast.** Open-Meteo
  400s a range running past its ~16-day window, so the agent requires both ends
  inside it; a trip starting in 12 days and ending in 21 falls back entirely to
  the seasonal proxy instead of splitting the range.
- **Agent output is English only.** A `language` field is threaded from the UI
  through to `TravelRequest`, defaulting to `en`; wiring the agent *prompts* to
  write their prose in French and Russian is pending. Advisory notes stay
  English by design (they're quoted from the State Dept feed, not authored).
- **Export filenames are ASCII-slugged.** Non-Latin country or city names slug
  to nothing and fall back to a generic filename. Latent until agent output is
  localised; the document contents are fully Unicode either way.
- **PDF pagination can leave a sparse page.** `fpdf2`'s `write_html` breaks
  early when a heading lands at the bottom margin. Cosmetic — no content is
  lost.

---

## Roadmap

The redesign is organised as four tracks; see `docs/rebuild_plan.md` for the
full 25-step breakdown.

### Foundations ✅
- [x] Hub-and-spoke state model — `enums.py`, `position.py`, conditional `intercity`
- [x] Commit-payload validation on write (`_COMMIT_SCHEMAS`, 422 on bad input)
- [x] Country agent (Claude + live advisory feed, disk-cached)
- [x] City agent (cities within the committed country)
- [x] Shared defensive JSON parsing (`ask_claude_json`)
- [x] Discovery failures surface as 502, not silent empty lists

### Track 1 — single city, end to end ✅
- [x] Country + City wizard stages (split from the old Destination stage)
- [x] Flights / accommodation / daily-plan moved to trip-level
- [x] Activities — preference, regenerate, expand, ordered picks
- [x] Real weather in the daily plan (live + seasonal proxy)
- [x] `budget_agent.aggregate()` — shared by CLI and wizard
- [x] `POST /trips/{id}/assemble` + final itinerary rendering
- [x] Final stage — renders, regenerates, commits

### Track 2 — multi-city ✅
- [x] "Add another city" — spoke list with reorder/remove
- [x] Intercity agent — hub↔spoke travel, web search + citations
- [x] Intercity stage — constrained date pickers
- [x] Activities loop across stops; assembly renders spokes
- [x] Budget includes intercity legs

### Track 3 — plans and sharing ✅
- [x] Trip list + resume (replaces auto-create)
- [x] Delete plans — multi-select, two-step confirm
- [x] Download the plan — Markdown and PDF
- [x] Free-text chat edits to the daily plan
- [x] Manual moves — activities between days, same-city only

### Track 4 — deployment ✅
- [x] Compress background images (PNG → WebP, ~93% smaller)
- [x] Mock hotel price correction
- [x] Geocode caching
- [x] Real RapidAPI providers verified end to end (Skyscanner, Booking)
- [x] Env-driven provider flags (were hardcoded, so unreachable)
- [x] Invite-code gate on registration
- [x] Dockerized deployment

### Deferred polish 📋
- [ ] Regenerate + preference text on the country stage
- [ ] Type-your-own country / city (`self_provided` commit path)
- [ ] Agent prose in French and Russian
- [ ] Google Calendar export
- [ ] Email sharing (confirm-before-send)
- [ ] Keyed geocoding with a real quota
- [ ] Split forecast: live for the near days, seasonal for the rest
- [ ] Distance-based mock flight estimates (the geocode cache has the coords)
- [ ] Per-option Skyscanner booking links (flag-on path)
- [ ] Log `plan.errors` in the degrading option fetchers
- [ ] Airbnb as a provider CHOICE on the Stay stage (hotel or Airbnb, then ten
      options from the chosen one). `AirbnbAgent` is never called from the
      wizard today — `options_adapter` doesn't import it — and either/or needs
      a provider field on a commit payload plus a migration, not the merge the
      append-based code was built for
- [ ] Rate limiting and a per-user trip quota

---

## Tech stack

**Backend** — Python 3.13 · Anthropic Claude (claude-sonnet-4-6) · FastAPI ·
PostgreSQL 16 · SQLAlchemy 2.x async (`asyncpg`) · Alembic · Pydantic v2 ·
python-jose (JWT) · bcrypt · httpx · geopy · fpdf2 · markdown · pytest

**Frontend** — React + Vite · Tailwind CSS · Framer Motion · Zustand ·
react-i18next (EN / FR / RU)

**External services** — RapidAPI (Skyscanner, Booking.com, Airbnb) · Open-Meteo
(no key) · U.S. State Department advisory feed (no key) · Docker (local Postgres)

---

## Contributing

Each step is a small, standalone Git commit. Follow the history to see every
design decision as it was made — including the reasoning behind schema choices,
state-machine tradeoffs, and the bugs found and fixed along the way. The
redesign plan lives in `docs/rebuild_plan.md`.