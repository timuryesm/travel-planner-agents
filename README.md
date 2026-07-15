# Travel Planner Agents

A multi-agent AI travel planning application with a stepwise wizard UI,
persistent state, and JWT authentication. Specialized agents handle each
planning domain — destinations, flights, hotels, weather, activities, and
budget — coordinated by a central orchestrator and a wizard state machine that
lets users navigate, skip, and revise each stage of their plan.

Built as a portfolio project targeting production-readiness: clean architecture,
resumable sessions, real external APIs, and a multilingual React frontend
(English / French / Russian).

---

## Architecture

### Phase A — agent pipeline (complete)

The original run-all-at-once pipeline. Still used for the final plan assembly.

```
User Input (budget, dates, destination, interests)
              │
              ▼
     ┌─────────────────┐
     │   Orchestrator  │  ← Claude plans execution order
     │     (Claude)    │
     └────────┬────────┘
              │ dispatches tasks
    ┌─────────┼──────────────────────────┐
    ▼         ▼          ▼              ▼
┌────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
│Weather │ │Flights │ │  Hotels  │ │Activities│
│ Agent  │ │ Agent  │ │  Agent   │ │  Agent   │
└────┬───┘ └───┬────┘ └────┬─────┘ └────┬─────┘
     │         │           │             │
     └─────────┴───────────┴─────────────┘
                           │
                    ┌──────▼──────┐
                    │   Budget    │
                    │    Agent    │  ← runs last
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  TravelPlan │  ← Pydantic state object
                    └──────┬──────┘
                           │
              ┌────────────▼────────────┐
              │   Structured Itinerary  │
              │   + Budget Breakdown    │
              │   + Booking Links       │
              └─────────────────────────┘
```

### Phase B — wizard state machine (complete)

Orchestration flips from run-all-at-once to a stepwise state machine.
The wizard pauses at every stage so the user can inspect, refine, or skip.
All state is persisted in Postgres between requests.

```
React Frontend
      │
      │  POST /trips/{id}/transition  { action: COMMIT | SKIP | FORWARD | BACK }
      ▼
┌─────────────────┐
│   FastAPI       │
│   (JWT auth)    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│              transition(trip, action)       │
│                                             │
│  COMMIT  → write commit row, advance        │
│  SKIP    → mark skipped, advance            │
│  FORWARD → advance (stays unvisited)        │
│  BACK    → invalidate_after cascade, jump   │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
  Stage agents     PostgreSQL
  (same as above,  (trips, stops,
   one at a time)   stage commits)
```

**Wizard stage sequence:**

```
setup → destination
  → [flights·1 → accommodation·1 → activities·1 → daily_plan·1]
  → [flights·2 → accommodation·2 → activities·2 → daily_plan·2]  ← multi-city
  → …
  → reconciliation → final
```

### Phase C — React frontend + agent endpoints (complete)

The frontend never talks to an agent directly. Four of the wizard's stages
need *proposed options* before the user can choose, and those come from a
single endpoint that runs the matching Phase A agent against committed wizard
state:

```
   Wizard stage mounts
          │
          │  POST /trips/{id}/stages/{stage}/options?stop_index=N
          ▼
   ┌──────────────────┐
   │  stage_options   │  ← validates stage, checks ownership,
   │     (route)      │    reads the setup commit
   └────────┬─────────┘
            │
            ▼
   ┌──────────────────┐
   │ options_adapter  │  ← builds a synthetic TravelPlan from
   │                  │    commit state (setup + stop.city)
   └────────┬─────────┘
            │  safe_run()
            ▼
   ┌──────────────────────────────────────────┐
   │  Destination │ Flight │ Hotel │ Activities│
   └────────┬─────────────────────────────────┘
            │
            ▼
    options[] shaped for that stage's commit payload
```

The adapter exists because the Phase A agents are built around a single-shot
`TravelPlan`, while the wizard's state is spread across commit rows. Rather
than rewrite the agents for the wizard (or the wizard for the agents), one
translation layer bridges them — so Phase A's agents stay usable by both the
CLI pipeline and the stepwise UI.

---

## Agents

| Agent | Data source | Fallback |
|---|---|---|
| **Orchestrator** | Claude (claude-sonnet-4-6) | Default sequential plan |
| **Destination** | Claude + U.S. State Dept advisory feed | Curated city list |
| **Weather** | Open-Meteo forecast / archive API | — |
| **Flights** | Skyscanner via RapidAPI | Realistic mock data |
| **Hotels** | Booking.com via RapidAPI | Realistic mock data |
| **Airbnb** | Airbnb19 via RapidAPI | Realistic mock data |
| **Activities** | Claude (LLM as tool) | — |
| **Budget** | Aggregates all agent results | — |

### Key design decisions

**Shared state over direct agent communication.** Agents never call each
other. They read from and write to a single `TravelPlan` Pydantic object.
This keeps agents independently testable and swappable.

**Single transition chokepoint.** All wizard navigation goes through one
function — `transition(trip, action)`. Forward gates, cascade-invalidate,
and future smart-invalidation are all one-place edits.

**JSONB + Pydantic as schema registry.** Each stage's commit payload is
stored as JSONB and validated at the application boundary by a typed
Pydantic schema. No separate table per stage; no over-normalized joins.

**Mock-first development.** Every agent with an external API dependency has
a realistic mock fallback. The full pipeline runs without any API keys.
Mocks are permanent production code, not scaffolding — they're the
degradation path, not a placeholder for one.

**Graceful degradation.** `safe_run()` in `BaseAgent` wraps every agent in
error handling. One failed API call never crashes the pipeline.

**Live signals over model memory.** The destination agent's safety notes come
from the current State Department advisory feed, never from the LLM. If the
lookup fails, the claim is dropped rather than guessed — stale or invented
safety guidance is worse than none.

**One definition per shape.** `Destination` is declared once in
`travel_plan.py` and re-exported from `schemas.py`, so the agent's output and
the wizard's commit payload validate against the same class and cannot drift.

---

## Project structure

```
travel-planner-agents/
├── src/
│   ├── agents/
│   │   ├── base_agent.py        ← shared contract all agents implement
│   │   ├── orchestrator.py      ← Claude-powered planning + assembly
│   │   ├── destination_agent.py ← Claude + live travel advisories
│   │   ├── weather_agent.py     ← Open-Meteo forecast/historical
│   │   ├── flight_agent.py      ← Skyscanner search + trip types
│   │   ├── hotel_agent.py       ← Booking.com + property type filter
│   │   ├── airbnb_agent.py      ← Airbnb listings + combined results
│   │   ├── activities_agent.py  ← Claude as tool
│   │   ├── budget_agent.py      ← aggregates all agent results
│   │   └── options_adapter.py   ← wizard commit state → TravelPlan agents
│   ├── api/
│   │   └── routes/
│   │       ├── auth.py          ← register / login
│   │       ├── trips.py         ← create / list / get / transition
│   │       └── stage_options.py ← runs an agent for one wizard stage
│   ├── auth/
│   │   └── jwt.py               ← token creation + get_current_user
│   ├── state/
│   │   ├── travel_plan.py       ← Pydantic models for agent data
│   │   ├── enums.py             ← CommitType, stage enums, TripStatus
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
├── alembic/
│   ├── env.py                   ← migration config (strips asyncpg for sync conn)
│   └── versions/
│       └── 0001_initial_schema.py  ← creates all 5 tables
├── docs/
│   ├── trip_state_model.md      ← wizard design spec (Phase B seed)
│   └── schema_design_notes.md   ← every non-obvious schema decision explained
├── tests/
│   ├── conftest.py              ← clears RapidAPI key → all tests use mocks
│   ├── test_travel_plan.py
│   ├── test_orchestrator.py
│   ├── test_weather_agent.py
│   ├── test_flight_agent.py
│   ├── test_hotel_agent.py
│   └── test_airbnb_agent.py
├── main.py                      ← CLI entry point (Phase A)
├── alembic.ini                  ← Alembic configuration
├── pyproject.toml
├── requirements.txt
└── .env.example
```

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/register` | Create account, returns JWT |
| `POST` | `/auth/login` | Form-encoded login, returns JWT |
| `POST` | `/trips/` | Create trip + 4 unvisited trip-stage commits |
| `GET` | `/trips/` | List the caller's trips |
| `GET` | `/trips/{id}` | Full trip state (position, commits, stops) |
| `POST` | `/trips/{id}/transition` | COMMIT / SKIP / FORWARD / BACK |
| `POST` | `/trips/{id}/stages/{stage}/options` | Run the stage's agent, return options |
| `GET` | `/health` | Liveness check |

Interactive docs at `/docs` (Swagger, with an Authorize button) and `/redoc`.

Trips are scoped to their owner: another user's trip returns 404, not 403 —
the API doesn't confirm the existence of resources you can't see.

---

## Setup

### 1. Clone and create virtual environment

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

Open `.env` and fill in:

```
ANTHROPIC_API_KEY=sk-ant-...        # console.anthropic.com
RAPIDAPI_KEY=...                    # rapidapi.com (one key for all APIs below)
DATABASE_URL=postgresql+asyncpg://travel:travel@localhost:5432/travel_planner
SECRET_KEY=...                      # any long random string for JWT signing
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

`DATABASE_URL` and `SECRET_KEY` are read at module import time and have no
defaults — a missing value fails fast at startup rather than silently
connecting somewhere unintended.

**Feature flags** (in `src/config/settings.py`, both default to `False`):

| Flag | Effect when `False` |
|---|---|
| `SKYSCANNER_ENABLED` | Flight agent returns mock data through the real code path |
| `AIRBNB_ENABLED` | Hotel agent returns mock data through the real code path |

These exist because the RapidAPI free tiers have small quotas that a
development loop exhausts quickly. The agents' mock paths are the same code
that runs on an API failure, so leaving the flags off exercises the real
degradation path rather than a special test mode.

### 4. Run database migrations

Migrations also run automatically on app startup, so this step is only needed
for the CLI pipeline or a fresh database inspected before first boot.

```bash
alembic upgrade head
```

This creates five tables: `users`, `trips`, `stops`, `trip_stage_commits`,
`stop_stage_commits`.

### 5. Subscribe to APIs on RapidAPI (optional — free tiers available)

| API | Used for | Host |
|---|---|---|
| Skyscanner | Flight search | `skyscanner-flights-travel-api.p.rapidapi.com` |
| Booking.com | Hotel search | `apidojo-booking-v1.p.rapidapi.com` |
| Airbnb | Airbnb listings | `airbnb19.p.rapidapi.com` |

All three use the same `RAPIDAPI_KEY`. The project works without any
RapidAPI subscriptions — mock data is used as fallback.

### 6. Run the backend

```bash
uvicorn src.main:app --reload
```

### 7. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server runs on `http://localhost:5173`. It reads the API base URL from
`VITE_API_BASE_URL` and defaults to `http://localhost:8000`, so no frontend
`.env` is needed for local development.

### 8. Run the Phase A CLI (optional)

```bash
python main.py
```

---

## Usage

### CLI (Phase A)

Edit the request in `main.py`:

```python
request = TravelRequest(
    destination="Tokyo",
    origin="Toronto",
    departure_date=date(2026, 8, 1),
    return_date=date(2026, 8, 10),
    budget_usd=4000.0,
    travelers=1,
    interests=["food", "temples", "hiking"],
    trip_type="roundtrip",
    accommodation_type="any",
    accommodation_providers=["booking.com", "airbnb"],
)
```

### Example output

```
============================================================
Planning trip: Toronto → Tokyo
Dates: 2026-08-01 → 2026-08-10  |  Budget: $4,000  |  Travelers: 1
============================================================

🌤  Weather in Tokyo (typical for this time of year):
    2026-08-01: Heavy drizzle, 24–30°C
    • Pack light, breathable clothing — it will be hot
    • Rain expected on 8 days — pack an umbrella

✈️  Best flight (roundtrip):
    Japan Airlines · Toronto → Tokyo (14.5h)
    Total price: $1,487.25
    Book: https://www.skyscanner.com/...

🏠  Best Entire 1-Bed Apt · via airbnb:
    Cozy Entire 1-Bed Apt in Shimokitazawa  ★★★★
    $95.40/night  ·  9 nights  ·  Total $858.60
    Book: https://www.airbnb.com/...
    (13 total: 6 from booking.com  |  7 from airbnb)
```

### Wizard (Phase B/C)

Register or log in, and the app opens on the setup stage. Each stage proposes
options, you choose one (or supply your own, or skip), and the backend advances
the position. The sidebar shows every stage and its commit state; clicking a
past stage warns about the blast radius before invalidating everything
downstream of it.

---

## Tests

```bash
python -m pytest tests/ -v
```

All agents have unit tests with mocked external API calls. A `conftest.py`
fixture clears the RapidAPI key, so tests run without internet access, without
any API keys, and without spending quota — fast, free, and deterministic.

---

## How it works

### Phase A — orchestration loop

```
1. User provides TravelRequest
2. Orchestrator calls Claude → returns ordered ExecutionPlan
3. Pipeline loops through tasks:
   - "weather"    → WeatherAgent (Open-Meteo)
   - "flights"    → FlightAgent (Skyscanner)
   - "hotels"     → HotelAgent + AirbnbAgent (based on provider preference)
   - "activities" → ActivitiesAgent (Claude)
   - "budget"     → BudgetAgent (aggregates all results)
4. Each agent reads TravelPlan, adds its results, marks itself complete
5. Orchestrator assembles final markdown itinerary
```

### Phase B/C — wizard transition loop

```
1. User authenticates (JWT)
2. POST /trips → creates Trip + 4 TripStageCommit rows (all unvisited)
3. For each wizard step:
   a. GET /trips/{id} → frontend reads current position + commit state
   b. POST /trips/{id}/stages/{stage}/options → agent proposes options
   c. User chooses → POST /trips/{id}/transition { action: COMMIT, data: ... }
   d. transition() writes commit row, calls advance(), updates position
4. Committing destinations creates one Stop row per city, each with four
   unvisited StopStageCommit rows — the stage sequence restructures itself
5. BACK action → invalidate_after() resets all downstream commits to unvisited
6. Reconciliation stage → nag for any skipped/unvisited stages
7. Final stage → orchestrator assembles plan from all chosen commits
```

---

## Database schema

Five tables in PostgreSQL. All PKs are UUIDs. Cascade-delete on all FKs.

```
users
  └── trips  (current_stage, current_stop_index, multi_city)
        ├── trip_stage_commits  (setup | destination | reconciliation | final)
        └── stops  (stop_index, city, country)
              └── stop_stage_commits  (flights | accommodation | activities | daily_plan)
```

Each commit row carries: `commit_type` (chosen / self_provided / skipped / unvisited),
`commit_data` (JSONB, typed by Pydantic schema), `self_provided_text`, `completed`.

See `docs/schema_design_notes.md` for the reasoning behind every non-obvious decision.

---

## Known limitations

Honest notes on what isn't finished, kept here rather than in a private list.

- **Agent calls block the event loop.** `stage_options.py` calls the
  synchronous agents directly from an async route. With the API feature flags
  off this is invisible (mock paths return instantly), but with Skyscanner
  enabled its polling loop would stall the whole server for the duration.
  Needs `run_in_threadpool`.
- **`safe_run()` masks failures as empty results.** An agent that raises
  produces a 200 response with `options: []`, indistinguishable from "no
  results found." This has already hidden one real bug.
- **Trips are auto-created on load.** The frontend mints a trip as soon as you
  authenticate, which is a placeholder for Phase D's trip list + resume flow.

---

## Roadmap

### Phase A — core agent engine ✅

- [x] Shared `TravelPlan` state model (Pydantic)
- [x] Orchestrator with Claude (structured JSON execution plan)
- [x] Weather agent (Open-Meteo forecast + historical proxy)
- [x] Flight agent (Skyscanner API, one-way / roundtrip / multi-city)
- [x] Hotel agent (Booking.com, all property types)
- [x] Airbnb agent (combined results across providers)
- [x] Activities agent (Claude as tool)
- [x] Budget agent (aggregates costs, checks against budget)
- [x] Mock fallback for all external APIs
- [x] Unit tests for all agents

### Phase B — FastAPI backend + PostgreSQL ✅

- [x] Trip state model design (`docs/trip_state_model.md`)
- [x] Pydantic commit schemas (`src/state/schemas.py`)
- [x] SQLAlchemy ORM models + Alembic migration (5 tables live in Postgres)
- [x] `Position` dataclass + `flattened_sequence()` + `positions_after()`
- [x] `transition()` function — COMMIT / SKIP / FORWARD / BACK + `invalidate_after()`
- [x] Trip repository — async DB layer (`create_trip`, `load_trip`, `save_commit`)
- [x] JWT auth — `hash_password`, `create_access_token`, `get_current_user`
- [x] FastAPI routes — `/auth/register`, `/auth/login`, `/trips`, `/trips/{id}/transition`
- [x] FastAPI app entrypoint (`src/main.py`)
- [x] Verified end-to-end against live Postgres

### Phase C — React frontend + agent endpoints ✅

- [x] Wizard UI — all 8 stages, step-by-step, live backend
- [x] English / French / Russian i18n via react-i18next
- [x] Results cards (flights, hotels, activities, daily plan)
- [x] Blast-radius warning before backward navigation
- [x] Photographic Toronto day/night background, CN Tower fireworks
- [x] Destination agent (Claude + live State Dept advisory signal)
- [x] `options_adapter` — wizard commit state → TravelPlan agents
- [x] `POST /trips/{id}/stages/{stage}/options`
- [x] All four option stages fetching from the live endpoint

### Phase D — plan editing + integrations 📋

- [ ] Trip list + resume flow (replaces auto-create)
- [ ] Free-text chat edits to daily plan
- [ ] Google Calendar export
- [ ] Email sharing (confirm-before-send)

### Phase E — deployment 📋

- [ ] Compress background images (PNG → WebP)
- [ ] Move agent calls off the event loop
- [ ] Dockerized deployment

---

## What this project teaches

| Concept | Where it appears |
|---|---|
| Agent-to-agent communication | Shared `TravelPlan` state object |
| Structured LLM output | Orchestrator JSON execution plan |
| Agent boundaries and contracts | `BaseAgent.safe_run()` pattern |
| Adapting an interface without rewriting either side | `options_adapter.py` |
| Graceful degradation | Mock fallbacks + error logging on plan |
| Grounding an LLM in a live source | Destination agent's advisory lookup |
| Cache-with-TTL over a rate-limited API | `tools/advisory_lookup.py` |
| Multi-provider data merging | Booking.com + Airbnb combined results |
| Wizard state machine | `transition()` + `invalidate_after()` |
| Cascade-invalidate | Backward navigation resets downstream commits |
| JSONB + Pydantic as schema registry | Per-stage commit_data payloads |
| Async SQLAlchemy | `AsyncSession`, `async_sessionmaker`, `asyncpg` |
| Database migrations | Alembic with hand-authored initial migration |
| JWT authentication | Stateless auth for resumable wizard sessions |
| External API integration | Skyscanner, Booking.com, Airbnb, Open-Meteo |
| Pydantic data validation | All inter-agent and API boundary data |
| Client-side request deduplication | In-flight promise cache in `client.js` |

---

## Tech stack

**Backend**

- **Python 3.11+**
- **Anthropic Claude** (claude-sonnet-4-6) — orchestration, destinations, activities
- **FastAPI** — async REST API
- **PostgreSQL 16** — persistent wizard state
- **SQLAlchemy 2.x** — async ORM (`asyncpg` driver)
- **Alembic** — database migrations
- **Pydantic v2** — data validation and state management
- **python-jose** — JWT auth
- **bcrypt** — password hashing (used directly, not via passlib)
- **httpx** — HTTP client
- **geopy** — city name → coordinates (weather agent)
- **pytest** — testing

**Frontend**

- **React** + **Vite**
- **Tailwind CSS** — styling
- **Framer Motion** — stage transitions and background animation
- **Zustand** — wizard state store
- **react-i18next** — EN / FR / RU

**External services**

- **RapidAPI** — Skyscanner, Booking.com, Airbnb
- **Open-Meteo** — free weather API (no key required)
- **U.S. State Department** — travel advisory feed (no key required)
- **Docker** — local Postgres

---

## Contributing

Each phase is a series of small, standalone Git commits. Follow the commit
history to see every design decision as it was made — including the reasoning
behind schema choices, state machine tradeoffs, and API integration fixes.

See `docs/trip_state_model.md` for the full wizard design spec, and
`docs/schema_design_notes.md` for the persistence layer rationale.