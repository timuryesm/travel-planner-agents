from datetime import date
from src.state.travel_plan import TravelPlan, TravelRequest
from src.agents.orchestrator import Orchestrator
from src.agents.weather_agent import WeatherAgent
from src.config.settings import settings
from src.agents.flight_agent import FlightAgent
from src.state.travel_plan import TravelPlan, TravelRequest, FlightOption
from src.agents.hotel_agent import HotelAgent


def run_pipeline(request: TravelRequest) -> TravelPlan:
    plan = TravelPlan(request=request)

    # Step 1: orchestrator plans
    orchestrator = Orchestrator()
    execution_plan = orchestrator.create_plan(plan)

    # Step 2: run agents in order
    # (for now only weather exists — others will be added in steps 5-7)
    agent_registry = {
        "weather": WeatherAgent(),
        "flights": FlightAgent(),
        "hotels":     HotelAgent(),
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

    if plan.selected_flight:
        f = plan.selected_flight
        print(f"\n✈️  Best flight ({f.trip_type.replace('_', '-')}):")
        _print_flight(f)
        if plan.flight_options:
            print(f"    ({len(plan.flight_options)} options found total)")

    if plan.selected_hotel:
        h     = plan.selected_hotel
        stars = "★" * int(h.stars or 0) if h.stars else "unrated"
        nights = (plan.request.return_date - plan.request.departure_date).days
        print(f"\n🏨  Best {h.property_type} ({h.provider}):")
        print(f"    {h.name}  {stars}")
        print(f"    {h.location}")
        print(f"    ${h.price_per_night_usd:,.2f}/night  ·  "
              f"{nights} nights  ·  Total ${h.total_price_usd:,.2f}")
        if h.booking_url:
            print(f"    Book: {h.booking_url}")
    if plan.hotel_options:
        types = {}
        for opt in plan.hotel_options:
            types[opt.property_type] = types.get(opt.property_type, 0) + 1
        summary = ", ".join(f"{v} {k}" for k, v in types.items())
        print(f"    ({len(plan.hotel_options)} options: {summary})")

    if plan.errors:
        print(f"\n⚠️  Errors:")
        for err in plan.errors:
            print(f"    {err}")

    print(f"\n✓ Completed agents: {', '.join(plan.completed_agents)}")


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