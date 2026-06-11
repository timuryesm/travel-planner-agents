from datetime import date
from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.orchestrator import Orchestrator
from src.config.settings import settings


def main():
    # Validate API keys are present before doing anything
    settings.validate()

    # Build a sample travel request
    request = TravelRequest(
        destination="Tokyo",
        origin="Toronto",
        departure_date=date(2025, 8, 1),
        return_date=date(2025, 8, 10),
        budget_usd=4000.0,
        travelers=1,
        interests=["food", "temples", "hiking"]
    )

    plan = TravelPlan(request=request)

    print("=" * 60)
    print(f"Planning trip: {request.origin} → {request.destination}")
    print(f"Dates: {request.departure_date} → {request.return_date}")
    print(f"Budget: ${request.budget_usd:,.0f} | Travelers: {request.travelers}")
    print(f"Interests: {', '.join(request.interests)}")
    print("=" * 60)

    orchestrator = Orchestrator()

    print("\nOrchestrator is planning...\n")
    execution_plan = orchestrator.create_plan(plan)

    print(f"Strategy: {execution_plan.strategy_notes}\n")
    print("Execution order:")
    for i, task in enumerate(execution_plan.tasks, 1):
        deps = f"  (after: {', '.join(task.depends_on)})" if task.depends_on else ""
        print(f"  {i}. {task.agent:<12} — {task.reason}{deps}")

    print("\n✓ Orchestrator planning complete.")
    print("  (Agents will be wired in Steps 4–7)")


if __name__ == "__main__":
    main()