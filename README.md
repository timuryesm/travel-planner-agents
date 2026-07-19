# Travel Planner Agents

A multi-agent AI travel-planning application with a stepwise wizard UI,
persistent state, and JWT authentication. Specialized agents handle each
planning domain — country, city, flights, hotels, weather, activities, and
budget — coordinated by a wizard state machine that lets users navigate, skip,
and revise each stage of their plan.

Built as a portfolio project targeting production-readiness: clean
architecture, resumable sessions, real external APIs, and a multilingual React
frontend (English / French / Russian).

> **Status:** mid-redesign. The project is moving from an early multi-city model
> to a **hub-and-spoke** one (see below). Track 1 — a single city planned all
> the way to a rendered itinerary — is nearly complete; multi-city, sharing, and
> deployment follow. The commit history is the source of truth for what's done.

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
   ┌────────────────────────────────────────────┐
   │  Country │ City │ Flight │ Hotel │ Activities│
   └────────┬───────────────────────────────────┘
            │
            ▼
    options[] shaped for that stage's commit payload
```

The adapter exists because the agents are built around a single-shot
`TravelPlan`, while the wizard's state is spread across commit rows. One
translation layer bridges them, so the same agents serve both the CLI pipeline
and the stepwise UI without either being rewritten for the other.

Weather is the exception: it's one object of context, not a list of options, so
it has its own read-only endpoint (`GET /trips/{id}/weather`) rather than going
through the options adapter.

Navigation and persistence go through a single function — `transition(trip,
action)` — which handles COMMIT / SKIP / FORWARD / BACK, validates each commit
payload against its stage's schema *before* writing, and cascade-invalidates
downstream stages on a backward jump.

---

## Agents

| Agent | Data source | On failure |
|---|---|---|
| **Country** | Claude + U.S. State Dept advisory feed | Curated country pool |
| **City** | Claude (within the committed country) | Raises — no honest generic answer |
| **Weather** | Open-Meteo forecast / archive API | Empty forecast, neutral note |
| **Flights** | Skyscanner via RapidAPI | Realistic mock data |
| **Hotels** | Booking.com via RapidAPI | Realistic mock data |
| **Airbnb** | Airbnb19 via RapidAPI | Realistic mock data |
| **Activities** | Claude | Curated activity pool |
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

---

## Agent JSON, weather, and advisories — the tricky bits

Three subsystems earned dedicated handling; each is documented at its source.

- **`tools/advisory_lookup.py`** — caches the State Dept feed (one document
  covering every country) on disk with a 6-hour TTL, matches countries by exact
  name rather than substring (so "Niger" never picks up "Nigeria"'s level),
  treats the feed's occasional empty `[]` response as a failure rather than
  data, and refuses to guess when a name is ambiguous.
- **`agents/weather_agent.py`** — geocodes the hub, uses a live forecast when
  the trip is within ~15 days, otherwise last year's same dates as a seasonal
  proxy (labelled *typical*). The route re-keys the proxy onto the trip's actual
  dates so the daily plan can look weather up by date.
- **`agents/base_agent.py`** — `ask_claude_json` and `safe_run`, described
  above.

---

## Project structure

```
travel-planner-agents/
├── src/
│   ├── agents/
│   │   ├── base_agent.py        ← shared contract + ask_claude_json + safe_run
│   │   ├── orchestrator.py      ← Claude-powered final assembly
│   │   ├── country_agent.py     ← Claude + live travel advisories
│   │   ├── city_agent.py        ← Claude, cities within the chosen country
│   │   ├── weather_agent.py     ← Open-Meteo forecast / seasonal proxy
│   │   ├── flight_agent.py      ← Skyscanner search (roundtrip origin↔hub)
│   │   ├── hotel_agent.py       ← Booking.com + property type filter
│   │   ├── airbnb_agent.py      ← Airbnb listings + combined results
│   │   ├── activities_agent.py  ← Claude; preference / regenerate / expand
│   │   ├── budget_agent.py      ← aggregates all agent results
│   │   └── options_adapter.py   ← wizard commit state → TravelPlan agents
│   ├── api/
│   │   └── routes/
│   │       ├── auth.py          ← register / login
│   │       ├── trips.py         ← create / list / get / transition
│   │       ├── stage_options.py ← runs an agent for one wizard stage
│   │       └── weather.py       ← per-day forecast for the hub
│   ├── auth/
│   │   └── jwt.py               ← token creation + get_current_user
│   ├── state/
│   │   ├── travel_plan.py       ← Pydantic models for agent data
│   │   ├── enums.py             ← CommitType, stage enums, TripStatus
│   │   ├── position.py          ← Position + flattened_sequence()
│   │   ├── transition.py        ← COMMIT/SKIP/FORWARD/BACK + validation
│   │   └── schemas.py           ← commit_data payload schemas per stage
│   ├── db/
│   │   ├── base.py              ← async engine, session factory, get_db
│   │   ├── models.py            ← User, Trip, Stop, TripStageCommit, StopStageCommit
│   │   └── trip_repository.py   ← async DB layer (create_trip, load_trip, …)
│   ├── tools/
│   │   ├── airport_lookup.py    ← IATA code lookup (API + fallback table)
│   │   └── advisory_lookup.py   ← cached State Dept advisory feed
│   ├── config/
│   │   ├── settings.py          ← environment variable loader + feature flags
│   │   └── logging_config.py    ← reclaims root logger after Alembic's fileConfig
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
│   │   │   └── wizard/          ← WizardRenderer + one component per stage
│   │   └── i18n/                ← EN / FR / RU translations
│   └── package.json
├── alembic/versions/           ← schema migrations
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
| `POST` | `/trips/{id}/transition` | COMMIT / SKIP / FORWARD / BACK |
| `POST` | `/trips/{id}/stages/{stage}/options` | Run the stage's agent, return options |
| `GET` | `/trips/{id}/weather` | Per-day forecast for the hub city |
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
- **Geocoding is unkeyed.** The weather agent uses Nominatim, which is rate-
  limited and has no API key. Fine for development; deployment needs a geocoder
  with a real quota.
- **Trips are auto-created on load.** The frontend mints a trip as soon as you
  authenticate — a placeholder for the trip-list + resume flow.
- **Agent output is English only.** A `language` field is threaded from the UI
  through to the request, defaulting to `en`; wiring the agent *prompts* to write
  their prose in French and Russian is pending. Advisory notes stay English (they
  come from the State Dept feed, not the model).

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

### Track 1 — single city, end to end 🚧
- [x] Country + City wizard stages (split from the old Destination stage)
- [x] Flights / accommodation / daily-plan moved to trip-level
- [x] Activities — preference, regenerate, expand, ordered picks
- [x] Real weather in the daily plan (live + seasonal proxy)
- [ ] `budget_agent.aggregate()` — shared by CLI and wizard
- [ ] `POST /trips/{id}/assemble` + final itinerary rendering
- [ ] Final stage — renders, regenerates, commits

### Track 2 — multi-city 📋
- [ ] "Add another city" — spoke list with reorder/remove
- [ ] Intercity agent — hub↔spoke travel, web search + citations
- [ ] Intercity stage — constrained date pickers
- [ ] Activities loop across stops; assembly renders spokes

### Track 3 — plans and sharing 📋
- [ ] Trip list + resume (replaces auto-create)
- [ ] Download the plan
- [ ] Google Calendar export
- [ ] Email sharing (confirm-before-send)
- [ ] Free-text chat edits to the daily plan

### Track 4 — deployment 📋
- [ ] Compress background images (PNG → WebP)
- [ ] Keyed geocoding
- [ ] Dockerized deployment

---

## Tech stack

**Backend** — Python 3.13 · Anthropic Claude (claude-sonnet-4-6) · FastAPI ·
PostgreSQL 16 · SQLAlchemy 2.x async (`asyncpg`) · Alembic · Pydantic v2 ·
python-jose (JWT) · bcrypt · httpx · geopy · pytest

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