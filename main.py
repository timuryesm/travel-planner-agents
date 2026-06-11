from datetime import date
from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.orchestrator import Orchestrator
from src.agents.weather_agent import WeatherAgent
from src.config.settings import settings


def run_pipeline(request: TravelRequest) -> TravelPlan:
    plan = TravelPlan(request=request)

    # Step 1: orchestrator plans
    orchestrator = Orchestrator()
    execution_plan = orchestrator.create_plan(plan)

    # Step 2: run agents in order
    # (for now only weather exists — others will be added in steps 5-7)
    agent_registry = {
        "weather": WeatherAgent(),
    }

    print(f"\nExecution plan: {execution_plan.strategy_notes}\n")

    for task in execution_plan.tasks:
        agent = agent_registry.get(task.agent)
        if agent:
            plan = agent.safe_run(plan)
        else:
            print(f"  ⏭  {task.agent} agent not implemented yet — skipping")

    return plan


def print_results(plan: TravelPlan) -> None:
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    if plan.weather:
        print(f"\n🌤  Weather in {plan.weather.location}:")
        for day, forecast in plan.weather.forecast_by_day.items():
            print(f"    {day}: {forecast}")
        print(f"\n  Packing tips:")
        for tip in plan.weather.packing_tips:
            print(f"    • {tip}")

    if plan.errors:
        print(f"\n⚠️  Errors:")
        for err in plan.errors:
            print(f"    {err}")

    print(f"\n✓ Completed agents: {', '.join(plan.completed_agents)}")


def main():
    settings.validate()

    request = TravelRequest(
        destination="Tokyo",
        origin="Toronto",
        departure_date=date(2026, 8, 1),
        return_date=date(2026, 8, 10),
        budget_usd=4000.0,
        travelers=1,
        interests=["food", "temples", "hiking"],
    )

    print("=" * 60)
    print(f"Planning trip: {request.origin} → {request.destination}")
    print(f"Dates: {request.departure_date} → {request.return_date}")
    print(f"Budget: ${request.budget_usd:,.0f} | Travelers: {request.travelers}")
    print(f"Interests: {', '.join(request.interests)}")
    print("=" * 60)

    plan = run_pipeline(request)
    print_results(plan)


if __name__ == "__main__":
    main()