# Travel Planner Agents

A multi-agent AI system that plans complete trips using specialized agents
coordinated by a central orchestrator. Each agent handles one domain —
flights, hotels, weather, activities, and budget — and communicates
through a shared state object.

Built as a learning project for multi-agent AI infrastructure, agent-to-agent
communication protocols, and complex task orchestration.

---

## Architecture

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
                    │  Shared     │
                    │  TravelPlan │  ← Pydantic state object
                    └──────┬──────┘
                           │
              ┌────────────▼────────────┐
              │   Structured Itinerary  │
              │   + Budget Breakdown    │
              │   + Booking Links       │
              └─────────────────────────┘
```

---

## Agents

| Agent | Data source | Fallback |
|---|---|---|
| **Orchestrator** | Claude (claude-sonnet-4-6) | Default sequential plan |
| **Weather** | Open-Meteo forecast / archive API | — |
| **Flights** | Skyscanner via RapidAPI | Realistic mock data |
| **Hotels** | Booking.com via RapidAPI | Realistic mock data |
| **Airbnb** | Airbnb13 via RapidAPI | Realistic mock data |
| **Activities** | Claude (LLM as tool) | — |
| **Budget** | Aggregates all agent results | — |

### Key design decisions

**Shared state over direct agent communication.** Agents never call each
other. They all read from and write to a single `TravelPlan` Pydantic
object. This makes agents independently testable and swappable.

**Every agent follows the same contract:**
```
read TravelPlan → call external API → parse result → write back to plan
```

**Mock-first development.** Every agent with an external API dependency has
a realistic mock fallback. The full pipeline runs without any API keys.

**Graceful degradation.** `safe_run()` in `BaseAgent` wraps every agent in
error handling. One failed API call never crashes the pipeline — the error
is logged on the plan and execution continues.

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
│   │   ├── activities_agent.py  ← coming in Step 7
│   │   └── budget_agent.py      ← coming in Step 7
│   ├── state/
│   │   └── travel_plan.py       ← Pydantic models for all shared data
│   ├── tools/
│   │   └── airport_lookup.py    ← IATA code lookup (API + fallback table)
│   └── config/
│       └── settings.py          ← environment variable loader
├── tests/
│   ├── test_travel_plan.py
│   ├── test_orchestrator.py
│   ├── test_weather_agent.py
│   ├── test_flight_agent.py
│   ├── test_hotel_agent.py
│   └── test_airbnb_agent.py
├── main.py                      ← CLI entry point
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

### 2. Configure API keys

```bash
cp .env.example .env
```

Open `.env` and fill in your keys:

```
ANTHROPIC_API_KEY=sk-ant-...        # console.anthropic.com
RAPIDAPI_KEY=...                    # rapidapi.com (one key covers all APIs below)
```

### 3. Subscribe to APIs on RapidAPI (free tiers available)

| API | Used for | Host |
|---|---|---|
| Skyscanner | Flight search | `skyscanner-flights-travel-api.p.rapidapi.com` |
| Booking.com | Hotel search | `apidojo-booking-v1.p.rapidapi.com` |
| Airbnb | Airbnb listings | `airbnb19.p.rapidapi.com` |

All three use the same `RAPIDAPI_KEY`. The project works without any
RapidAPI subscriptions — mock data is used as fallback.

### 4. Run

```bash
python main.py
```

---

## Usage

Edit the request in `main.py` to plan any trip:

```python
request = TravelRequest(
    destination="Tokyo",
    origin="Toronto",
    departure_date=date(2026, 8, 1),
    return_date=date(2026, 8, 10),
    budget_usd=4000.0,
    travelers=1,
    interests=["food", "temples", "hiking"],

    # Trip type: "one_way" | "roundtrip" | "multi_city"
    trip_type="roundtrip",

    # Accommodation type: "any" | "hotel" | "apartment" | "hostel" | "villa"
    accommodation_type="any",

    # Providers: any combination of ["booking.com", "airbnb"]
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
    ...
    • Pack light, breathable clothing — it will be hot
    • Rain expected on 8 days — pack an umbrella

✈️  Best flight (roundtrip):
    Japan Airlines
    Outbound : Toronto → Tokyo
               Departs 2026-08-01T17:00 local  →  Arrives 2026-08-02T20:30 local  (14.5h)
    Return   : Tokyo → Toronto
               Departs 2026-08-10T11:00 local  →  Arrives 2026-08-10T09:30 local  (14.5h)
    Total price: $1,487.25
    Book: https://www.skyscanner.com/transport/flights/ytoa/tyoa/260801/260810/...

🏠  Best Entire 1-Bed Apt · via airbnb:
    Cozy Entire 1-Bed Apt in Shimokitazawa  ★★★★
    Shimokitazawa, Tokyo
    $95.40/night  ·  9 nights  ·  Total $858.60
    Book: https://www.airbnb.com/s/Tokyo--Japan/homes?...
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

## How it works — the orchestration loop

```
1. User provides TravelRequest
2. Orchestrator calls Claude → returns ordered ExecutionPlan
3. Pipeline loops through tasks:
   - "weather"    → WeatherAgent (Open-Meteo)
   - "flights"    → FlightAgent (Skyscanner)
   - "hotels"     → HotelAgent + AirbnbAgent (based on providers preference)
   - "activities" → ActivitiesAgent (Claude)
   - "budget"     → BudgetAgent (aggregates all results)
4. Each agent reads TravelPlan, adds its results, marks itself complete
5. Orchestrator assembles final markdown itinerary
```

---

## Roadmap

### Done ✅
- [x] Shared `TravelPlan` state model (Pydantic)
- [x] Orchestrator with Claude (structured JSON execution plan)
- [x] Weather agent (Open-Meteo forecast + historical proxy)
- [x] Flight agent (Skyscanner API, one-way / roundtrip / multi-city)
- [x] Hotel agent (Booking.com, all property types)
- [x] Airbnb agent (combined results across providers)
- [x] Mock fallback for all external APIs
- [x] Unit tests for all agents

### In progress 🔄
- [ ] Activities agent (Claude as tool — curates local experiences)
- [ ] Budget agent (aggregates costs, checks against budget)
- [ ] Final itinerary assembly (Orchestrator `assemble_itinerary`)

### Planned 📋
- [ ] Streamlit UI (form input, tabbed output, booking links)
- [ ] Async agent execution with `asyncio` (parallel agent runs)
- [ ] Reasoning graph visualizer (agent interaction diagram)
- [ ] Google Calendar integration (block travel dates)
- [ ] Group planning mode (multiple users negotiate a trip)
- [ ] Browser extension (auto-fill itinerary on booking sites)

---

## What this project teaches

| Concept | Where it appears |
|---|---|
| Agent-to-agent communication | Shared `TravelPlan` state object |
| Structured LLM output | Orchestrator JSON execution plan |
| Agent boundaries and contracts | `BaseAgent.safe_run()` pattern |
| Graceful degradation | Mock fallbacks + error logging on plan |
| Multi-provider data merging | Booking.com + Airbnb combined results |
| External API integration | Skyscanner, Booking.com, Open-Meteo |
| Pydantic data validation | All inter-agent data transfer |
| Dependency management | `depends_on` in `ExecutionPlan` tasks |

---

## Tech stack

- **Python 3.11+**
- **Anthropic Claude** — orchestration and activities
- **Pydantic v2** — data validation and state management
- **httpx** — async-ready HTTP client
- **geopy** — city name → coordinates (weather agent)
- **RapidAPI** — Skyscanner, Booking.com, Airbnb
- **Open-Meteo** — free weather API (no key required)
- **pytest** — testing

---

## Contributing

This is a learning project. Each step is a standalone Git commit so you
can follow the build history to understand how the system evolved.

See commit history for a step-by-step walkthrough of every design decision.