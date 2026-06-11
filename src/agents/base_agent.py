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
        Wraps run() with error handling so one agent failure
        never crashes the whole pipeline.
        """
        self.logger.info(f"Starting")
        try:
            result = self.run(plan)
            self.logger.info(f"Complete")
            return result
        except Exception as e:
            self.logger.error(f"Failed: {e}")
            plan.add_error(self.name, str(e))
            return plan