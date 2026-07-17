from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from src.state.travel_plan import TravelPlan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-20s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)


class BaseAgent(ABC):
    """
    Every specialist agent inherits from this.
    Enforces the read → fetch → parse → write contract.
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier — must match the name used in ExecutionPlan tasks."""
        ...

    @abstractmethod
    def run(self, plan: TravelPlan) -> TravelPlan:
        """
        Execute this agent's work.
        Always receives the full TravelPlan, always returns it enriched.
        """
        ...

    def safe_run(self, plan: TravelPlan) -> TravelPlan:
        """
        Wraps run() with error handling so one agent failure never crashes the
        whole pipeline.

        The degradation is deliberate — a flight lookup dying should not lose
        the user the country they already chose — but it has a cost worth being
        explicit about: the plan comes back with its result field still None,
        the adapter reads `plan.flight_options or []`, and the route answers
        200 with an empty list. From the browser, "the agent crashed" and "the
        agent found nothing" are the same event. That has already hidden two
        bugs: DestinationAgent assigning an undeclared Pydantic field, and
        advisory_lookup raising on an unexpected feed shape.

        So the traceback is non-negotiable. logger.exception (not .error) is
        what makes the failure visible in the uvicorn log, which is the only
        place it can be seen at all. Read the log, not the response, when an
        options list comes back empty.

        plan.errors also carries the message onward, and is the hook if we ever
        want the route to distinguish the two cases and return a 5xx — see the
        note in the module docstring of options_adapter.
        """
        self.logger.info("Starting")
        try:
            result = self.run(plan)
            self.logger.info("Complete")
            return result
        except Exception as e:
            # .exception, not .error: this logs the traceback. Without it the
            # message alone tells you an agent failed but not where, and the
            # exception object is gone by the time the route sees the plan.
            self.logger.exception(f"Failed: {e}")
            plan.add_error(self.name, str(e))
            return plan