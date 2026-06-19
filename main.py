from datetime import date
from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.orchestrator import Orchestrator
from src.agents.weather_agent import WeatherAgent
from src.config.settings import settings
from src.agents.flight_agent import FlightAgent
from src.state.travel_plan import TravelPlan, TravelRequest, FlightOption
from src.agents.hotel_agent import HotelAgent
from src.agents.airbnb_agent import AirbnbAgent
from src.agents.activities_agent import ActivitiesAgent
from src.agents.budget_agent import BudgetAgent

def run_pipeline(request: TravelRequest) -> TravelPlan:
    plan = TravelPlan(request=request)
    orchestrator = Orchestrator()
    execution_plan = orchestrator.create_plan(plan)

    # Agents that map 1:1 with orchestrator task names
    agent_registry = {
        "weather":    WeatherAgent(),
        "flights":    FlightAgent(),
        "activities": ActivitiesAgent(),
        "budget":     BudgetAgent(),
    }

    print(f"\nExecution plan: {execution_plan.strategy_notes}\n")

    for task in execution_plan.tasks:

        # "hotels" maps to one or more providers based on user preference
        if task.agent == "hotels":
            providers = request.accommodation_providers
            if "booking.com" in providers or "all" in providers:
                plan = HotelAgent().safe_run(plan)
            if "airbnb" in providers or "all" in providers:
                plan = AirbnbAgent().safe_run(plan)
            if not plan.hotel_options:
                print(f"  ⚠️  No accommodation results from any provider")

        elif task.agent in agent_registry and agent_registry[task.agent]:
            plan = agent_registry[task.agent].safe_run(plan)

        else:
            print(f"  ⏭  {task.agent} agent not implemented yet — skipping")

    # After all agents have run, assemble the final itinerary
    if plan.is_ready_for_output():
        plan.itinerary_markdown = orchestrator.assemble_itinerary(plan)
    else:
        missing = {"weather", "flights", "hotels", "activities", "budget"} - set(plan.completed_agents)
        print(f"\n⚠️  Skipping itinerary assembly — missing agents: {', '.join(missing)}")

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

    if plan.selected_flight:
        f = plan.selected_flight
        print(f"\n✈️  Best flight ({f.trip_type.replace('_', '-')}):")
        _print_flight(f)
        if plan.flight_options:
            print(f"    ({len(plan.flight_options)} options found total)")

    if plan.selected_hotel:
        h      = plan.selected_hotel
        stars  = "★" * int(h.stars or 0) if h.stars else "no rating"
        nights = (plan.request.return_date - plan.request.departure_date).days
        icon   = "🏠" if h.provider == "airbnb" else "🏨"
        print(f"\n{icon}  Best {h.property_type} · via {h.provider}:")
        print(f"    {h.name}  {stars}")
        print(f"    {h.location}")
        print(f"    ${h.price_per_night_usd:,.2f}/night  ·  "
              f"{nights} nights  ·  Total ${h.total_price_usd:,.2f}")
        if h.booking_url:
            print(f"    Book: {h.booking_url}")

    if plan.hotel_options:
        by_provider: dict[str, int] = {}
        for opt in plan.hotel_options:
            by_provider[opt.provider] = by_provider.get(opt.provider, 0) + 1
        summary = "  |  ".join(
            f"{v} from {k}" for k, v in by_provider.items()
        )
        print(f"    ({len(plan.hotel_options)} total: {summary})")

    if plan.errors:
        print(f"\n⚠️  Errors:")
        for err in plan.errors:
            print(f"    {err}")

    print(f"\n✓ Completed agents: {', '.join(plan.completed_agents)}")

    if plan.activities:
        print(f"\n🎟  Activities ({len(plan.activities)}):")
        for a in plan.activities:
            cost = "Free" if a.estimated_cost_usd == 0 else f"${a.estimated_cost_usd:,.0f}"
            print(f"    • {a.name}  [{a.category}]")
            print(f"      {a.description}")
            print(f"      {cost} · {a.duration_hours}h")

    if plan.budget:
        b = plan.budget
        status = "✅ Within budget" if b.within_budget else "❌ Over budget"
        print(f"\n💰  Budget breakdown:")
        print(f"    Flights:        ${b.flights_usd:>10,.2f}")
        print(f"    Accommodation:  ${b.hotel_usd:>10,.2f}")
        print(f"    Activities:     ${b.activities_usd:>10,.2f}")
        print(f"    Miscellaneous:  ${b.miscellaneous_usd:>10,.2f}")
        print(f"    {'─' * 30}")
        print(f"    TOTAL:          ${b.total_usd:>10,.2f}")
        print(f"    Budget:         ${plan.request.budget_usd:>10,.2f}")
        print(f"    {status}")
        for note in b.notes:
            print(f"    • {note}")

    # Final assembled itinerary
    if plan.itinerary_markdown:
        print("\n" + "=" * 60)
        print("YOUR ITINERARY")
        print("=" * 60 + "\n")
        print(plan.itinerary_markdown)

        # Save to a markdown file
        from pathlib import Path
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        filename = output_dir / (
            f"itinerary_{plan.request.destination.lower().replace(' ', '_')}_"
            f"{plan.request.departure_date}.md"
        )
        filename.write_text(plan.itinerary_markdown, encoding="utf-8")
        print(f"\n💾 Saved to {filename}")


def _print_flight(f: "FlightOption") -> None:
    if f.trip_type == "one_way":
        leg = f.legs[0]
        print(f"    {leg.airline}")
        print(f"    {leg.origin} → {leg.destination}")
        print(f"    Departs: {leg.departure_time}  Arrives: {leg.arrival_time}")
        print(f"    Duration: {leg.duration_hours}h  |  Price: ${f.price_usd:,.2f}")

    elif f.trip_type == "roundtrip":
        out, ret = f.legs[0], f.legs[1]
        print(f"    {out.airline}")
        print(f"    Outbound : {out.origin} → {out.destination}")
        print(f"               Departs {out.departure_time} local"
              f"  →  Arrives {out.arrival_time} local  ({out.duration_hours}h)")
        print(f"    Return   : {ret.origin} → {ret.destination}")
        print(f"               Departs {ret.departure_time} local"
              f"  →  Arrives {ret.arrival_time} local  ({ret.duration_hours}h)")
        print(f"    Total price: ${f.price_usd:,.2f}")

    elif f.trip_type == "multi_city":
        for i, leg in enumerate(f.legs, 1):
            print(f"    Leg {i}: {leg.origin} → {leg.destination}  |  {leg.airline}")
            print(f"           Departs {leg.departure_time}  "
                  f"Arrives {leg.arrival_time}  ({leg.duration_hours}h)")
        print(f"    Total price: ${f.price_usd:,.2f}")

    if f.booking_url:
        print(f"    Book: {f.booking_url}")


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
        accommodation_type="any",   # try: "hotel", "apartment", "hostel", "any"
        accommodation_providers=["booking.com", "airbnb"]
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