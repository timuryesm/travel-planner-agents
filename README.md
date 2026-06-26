# Travel Planner Agents

A multi-agent AI travel planning application with a stepwise wizard UI,
persistent state, and JWT authentication. Specialized agents handle each
planning domain — flights, hotels, weather, activities, and budget — coordinated
by a central orchestrator and a wizard state machine that lets users navigate,
skip, and revise each stage of their plan.

Built as a portfolio project targeting production-readiness: clean architecture,
resumable sessions, real external APIs, and a multilingual React frontend (English / Russian).

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

### Phase B — wizard state machine (in progress)

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
│              transition(trip, action)        │
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

---

## Agents

| Agent | Data source | Fallback |
|---|---|---|
| **Orchestrator** | Claude (claude-sonnet-4-6) | Default sequential plan |
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

**Graceful degradation.** `safe_run()` in `BaseAgent` wraps every agent in
error handling. One failed API call never crashes the pipeline.

---

## Project structure

```
travel-planner-agents/
├── src/
│   ├── agents/
│   │   ├── base_agent.py        ← shared contract all agents implement
│   │   ├── orchestrator.py      ← Claude-powered planning + assembly
│   │   ├── weather_agent.py     ← Open-Meteo forecast/historical
│   │   ├── flight_agent.py      ← Skyscanner search + trip types
│   │   ├── hotel_agent.py       ← Booking.com + property type filter
│   │   ├── airbnb_agent.py      ← Airbnb listings + combined results
│   │   ├── activities_agent.py  ← Claude as tool
│   │   └── budget_agent.py      ← aggregates all agent results
│   ├── state/
│   │   ├── travel_plan.py       ← Pydantic models for agent data (Phase A)
│   │   ├── enums.py             ← CommitType, stage enums, TripStatus (Phase B)
│   │   └── schemas.py           ← commit_data payload schemas per stage (Phase B)
│   ├── db/                      ← Phase B
│   │   ├── base.py              ← async engine, session factory, get_db
│   │   └── models.py            ← User, Trip, Stop, TripStageCommit, StopStageCommit
│   ├── tools/
│   │   └── airport_lookup.py    ← IATA code lookup (API + fallback table)
│   └── config/
│       └── settings.py          ← environment variable loader
├── alembic/                     ← Phase B
│   ├── env.py                   ← migration config (strips asyncpg for sync conn)
│   └── versions/
│       └── 0001_initial_schema.py  ← creates all 5 tables
├── docs/
│   ├── trip_state_model.md      ← wizard design spec (Phase B seed)
│   └── schema_design_notes.md   ← every non-obvious schema decision explained
├── tests/
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
```

### 4. Run database migrations

```bash
alembic upgrade head
```

This creates five tables: `users`, `trips`, `stops`, `trip_stage_commits`,
`stop_stage_commits`.

### 5. Subscribe to APIs on RapidAPI (free tiers available)

| API | Used for | Host |
|---|---|---|
| Skyscanner | Flight search | `skyscanner-flights-travel-api.p.rapidapi.com` |
| Booking.com | Hotel search | `apidojo-booking-v1.p.rapidapi.com` |
| Airbnb | Airbnb listings | `airbnb19.p.rapidapi.com` |

All three use the same `RAPIDAPI_KEY`. The project works without any
RapidAPI subscriptions — mock data is used as fallback.

### 6. Run

```bash
# Phase A — CLI pipeline
python main.py

# Phase B — FastAPI server (coming soon)
uvicorn src.main:app --reload
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

---

## Tests

```bash
python -m pytest tests/ -v
```

All agents have unit tests with mocked external API calls. Tests run
without internet access and without any API keys.

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

### Phase B — wizard transition loop

```
1. User authenticates (JWT)
2. POST /trips → creates Trip + 4 TripStageCommit rows (all unvisited)
3. For each wizard step:
   a. GET /trips/{id} → frontend reads current position + commit state
   b. AI/API agent proposes options for current stage
   c. User chooses → POST /trips/{id}/transition { action: COMMIT, data: ... }
   d. transition() writes commit row, calls advance(), updates position
4. BACK action → invalidate_after() resets all downstream commits to unvisited
5. Reconciliation stage → nag for any skipped/unvisited stages
6. Final stage → orchestrator assembles plan from all chosen commits
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

### Phase B — FastAPI backend + PostgreSQL 🔄

- [x] Trip state model design (`docs/trip_state_model.md`)
- [x] Pydantic commit schemas (`src/state/schemas.py`)
- [x] SQLAlchemy ORM models + Alembic migration (5 tables live in Postgres)
- [ ] `Position` dataclass + `flattened_sequence()` + `positions_after()`
- [ ] `transition()` function — COMMIT / SKIP / FORWARD / BACK + `invalidate_after()`
- [ ] Trip repository — async DB layer (`create_trip`, `load_trip`, `save_commit`)
- [ ] JWT auth — `hash_password`, `create_access_token`, `get_current_user`
- [ ] FastAPI routes — `/auth/register`, `/auth/login`, `/trips`, `/trips/{id}/transition`
- [ ] FastAPI app entrypoint (`src/main.py`)

### Phase C — React frontend 📋

- [ ] Wizard UI (step-by-step form, stage navigation)
- [ ] English / Russian i18n via react-i18next
- [ ] Results cards (flights, hotels, activities, daily plan)
- [ ] Blast-radius warning before backward navigation

### Phase D — plan editing + integrations 📋

- [ ] Free-text chat edits to daily plan
- [ ] Google Calendar export
- [ ] Email sharing (confirm-before-send)

### Phase E — world map + deployment 📋

- [ ] Best-destination color-coded world map
- [ ] Dockerized deployment

---

## What this project teaches

| Concept | Where it appears |
|---|---|
| Agent-to-agent communication | Shared `TravelPlan` state object |
| Structured LLM output | Orchestrator JSON execution plan |
| Agent boundaries and contracts | `BaseAgent.safe_run()` pattern |
| Graceful degradation | Mock fallbacks + error logging on plan |
| Multi-provider data merging | Booking.com + Airbnb combined results |
| Wizard state machine | `transition()` + `invalidate_after()` |
| Cascade-invalidate | Backward navigation resets downstream commits |
| JSONB + Pydantic as schema registry | Per-stage commit_data payloads |
| Async SQLAlchemy | `AsyncSession`, `async_sessionmaker`, `asyncpg` |
| Database migrations | Alembic with hand-authored initial migration |
| JWT authentication | Stateless auth for resumable wizard sessions |
| External API integration | Skyscanner, Booking.com, Airbnb, Open-Meteo |
| Pydantic data validation | All inter-agent and API boundary data |

---

## Tech stack

- **Python 3.11+**
- **Anthropic Claude** (claude-sonnet-4-6) — orchestration and activities
- **FastAPI** — async REST API (Phase B)
- **PostgreSQL 16** — persistent wizard state
- **SQLAlchemy 2.x** — async ORM (`asyncpg` driver)
- **Alembic** — database migrations
- **Pydantic v2** — data validation and state management
- **python-jose** — JWT auth (Phase B)
- **passlib[bcrypt]** — password hashing (Phase B)
- **httpx** — async HTTP client
- **geopy** — city name → coordinates (weather agent)
- **RapidAPI** — Skyscanner, Booking.com, Airbnb
- **Open-Meteo** — free weather API (no key required)
- **pytest** — testing
- **Docker** — local Postgres

---

## Contributing

Each phase is a series of small, standalone Git commits. Follow the commit
history to see every design decision as it was made — including the reasoning
behind schema choices, state machine tradeoffs, and API integration fixes.

See `docs/trip_state_model.md` for the full wizard design spec, and
`docs/schema_design_notes.md` for the persistence layer rationale.