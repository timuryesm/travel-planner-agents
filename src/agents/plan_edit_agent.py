from __future__ import annotations

from src.agents.base_agent import BaseAgent


class PlanEditAgent(BaseAgent):
    """
    Turns "move the museum to Thursday" into structured operations.

    Ops, not a rewritten plan. Asking Claude to return the whole day_by_day
    list makes every failure total: a hallucinated activity name, a dropped
    day, or an invented date corrupts the entire plan and the user cannot see
    what changed. Ops fail individually — an op naming an activity that isn't
    on the trip is rejected and reported, and the rest still apply.

    It also keeps the rules in code. The same-city constraint (a spoke day IS
    the day trip, so its activities cannot move to a hub day) is enforced by
    the applier, not by hoping the model respected an instruction.

    NO FALLBACK, unlike ActivitiesAgent. A generic activity list is an honest
    answer when suggestion fails; there is no generic answer to "what did this
    user mean". Returning an empty op list on failure would read as "your
    request was understood and changed nothing", which is a lie. The agent
    raises and the route turns it into a 502 the component can retry.

    Two op types for now:

      move    reposition an activity onto a given date (start or end of day)
      remove  take an activity off the plan entirely

    Deliberately no "add": the only activities that may appear are the ones
    committed at the activities stage, and re-adding a removed one is better
    served by going BACK to that stage than by an agent inventing entries.
    """

    name = "plan_edit"

    def __init__(self, day_by_day: list[dict], message: str):
        super().__init__()
        self.day_by_day = day_by_day
        self.message = message

    def run(self, plan=None):
        """
        Not the usual TravelPlan-in/TravelPlan-out shape: this agent edits a
        daily plan the wizard holds locally and never touches TravelPlan. The
        route calls generate_ops() directly; run() exists only so the class
        satisfies BaseAgent's interface.
        """
        raise NotImplementedError("Use generate_ops(); this agent is route-driven.")

    def generate_ops(self) -> dict:
        self.logger.info(
            f"Interpreting plan edit over {len(self.day_by_day)} days: "
            f"{self.message[:80]!r}"
        )

        system_prompt = """You convert a traveler's plain-language request into edits on their daily itinerary.

Return ONLY valid JSON, no markdown, no backticks, no explanation.

Structure:
{
  "ops": [
    {"op": "move", "activity": "exact activity name", "to_date": "YYYY-MM-DD", "position": "start"},
    {"op": "remove", "activity": "exact activity name"}
  ],
  "note": "One short sentence describing what you changed, in the traveler's own terms."
}

Rules:
- "activity" MUST copy an activity name exactly as it appears in the plan. Never invent or paraphrase one.
- "to_date" MUST be one of the dates listed in the plan.
- "position" is "start" or "end" — where in that day's list it lands. Default "end".
- Only emit ops the request actually asks for. An unclear request gets an empty ops list and a note saying what was unclear.
- Never reorder days themselves; days are fixed to their dates.
- Each day is labelled with its city. Moving an activity to a day in a DIFFERENT city is not possible — if that is what was asked, return no op for it and say so in the note."""

        lines = ["Current plan:"]
        for day in self.day_by_day:
            names = day.get("activity_names") or []
            listed = "; ".join(names) if names else "(nothing scheduled)"
            lines.append(f"- {day.get('date')} ({day.get('city')}): {listed}")

        lines.append("")
        lines.append(f'Their request: "{self.message}"')

        data = self.ask_claude_json(
            system_prompt=system_prompt,
            user_message="\n".join(lines),
        )

        ops = data.get("ops")
        if not isinstance(ops, list):
            raise ValueError("Response had no 'ops' list")

        return {"ops": ops, "note": str(data.get("note") or "").strip()}