# Travel Planner Agents

A multi-agent AI system that plans complete trips using specialized agents
for flights, hotels, activities, weather, and budgeting — coordinated by
a central orchestrator.

## Architecture

- **Orchestrator** — breaks down the user request and coordinates agents
- **Flight agent** — searches Skyscanner for the best options
- **Hotel agent** — queries Booking.com for accommodation
- **Weather agent** — fetches forecasts for travel dates
- **Activities agent** — curates local experiences using Claude
- **Budget agent** — aggregates all costs into a structured breakdown

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in your API keys in .env
python main.py
```

## Project status

Step 1 complete — scaffold and repo setup.