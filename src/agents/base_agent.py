from __future__ import annotations
import json
import logging
import re
from abc import ABC, abstractmethod

import anthropic

from src.config.settings import settings
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

    # Overridable per agent. Declared here because ask_claude_json needs a
    # model and every Claude-backed agent was declaring the same string.
    MODEL: str = "claude-sonnet-4-6"

    # Attempts for ask_claude_json. Two, not more: the failure this guards
    # against is a formatting slip, which a second roll almost always fixes. A
    # real outage should surface as an error rather than as four slow retries.
    JSON_ATTEMPTS: int = 2

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

    # ── Claude JSON ──────────────────────────────────────────────────────

    def ask_claude_json(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 2048,
        attempts: int | None = None,
    ) -> dict:
        """
        Ask Claude for JSON and return it parsed. Raises if it can't be had.

        Every agent that asks Claude for structured data was doing this by
        hand: system prompt says "no markdown, no backticks", then
        json.loads(response.content[0].text). That works until the model wraps
        the object in a fence anyway, at which point json.loads dies on
        character zero with "Expecting value: line 1 column 1". Observed live
        on the city stage.

        The consequences differed per agent, and that's the real reason this is
        shared. CityAgent raised, which is honest. CountryAgent and
        ActivitiesAgent caught the parse error and served their hardcoded
        fallback — so a formatting slip silently replaced Claude's tailored
        suggestions with a canned list, at a WARNING nobody was reading. The
        output looked entirely plausible. Fiction, delivered confidently, is
        the failure mode this codebase keeps deciding against.

        Why not assistant prefill: ending the message list with
        {"role": "assistant", "content": "{"} would make a fence structurally
        impossible, and it is the standard trick. claude-sonnet-4-6 rejects it —
        400, "This model does not support assistant message prefill. The
        conversation must end with a user message." So we parse defensively
        instead: strip a fence if present, and failing that, take the outermost
        {...} span. Less elegant, and it will need extending if the model
        invents a new way to be helpful. The retry is what covers that gap.

        Retries are for TRANSIENT failures only — parse errors, timeouts,
        429s, 5xx. A 400 is deterministic: the same request will be malformed
        the second time too, so retrying it only doubles the latency of
        failing. That distinction cost a debugging round when the prefill 400
        above was retried instead of surfaced.

        Raises RuntimeError if every attempt fails. Callers decide whether that
        means a fallback (flights, activities — there is something honest to
        degrade to) or an error (cities — there isn't).
        """
        attempts = attempts or self.JSON_ATTEMPTS
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = client.messages.create(
                    model=self.MODEL,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                )
                if response.stop_reason == "max_tokens":
                    # The JSON is truncated and unparseable. Say why, rather
                    # than letting it surface as an opaque decode error.
                    raise ValueError(
                        f"Response hit max_tokens ({max_tokens}) and is "
                        f"truncated — raise the limit or ask for fewer items"
                    )
                return self._parse_json(response.content[0].text)

            except anthropic.APIStatusError as e:
                # 4xx that isn't rate limiting: our request is wrong. Retrying
                # an identical bad request is pointless.
                if e.status_code < 500 and e.status_code != 429:
                    raise
                last_error = e
            except Exception as e:
                last_error = e

            if attempt < attempts:
                self.logger.warning(
                    f"Claude JSON attempt {attempt}/{attempts} failed "
                    f"({type(last_error).__name__}: {last_error}) — retrying"
                )

        raise RuntimeError(
            f"Claude did not return usable JSON after {attempts} attempts: "
            f"{last_error}"
        ) from last_error

    def _parse_json(self, raw: str) -> dict:
        """
        Parse Claude's text as JSON, tolerating the two things it actually does.

        1. Markdown fences: ```json\n{...}\n```
        2. Prose around the object: "Here's the JSON:\n{...}\nHope this helps!"

        The outermost-span fallback (first { to last }) is deliberately blunt.
        It cannot recover a truncated object — the last brace lands mid-
        structure and the parse fails again, which is correct. Half an object is
        not an answer.
        """
        text = raw.strip()

        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
            self.logger.debug("Stripped a markdown fence from Claude's JSON")

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start == -1 or end <= start:
                raise
            parsed = json.loads(text[start : end + 1])
            self.logger.warning(
                "Claude's JSON had text around the object — salvaged the span"
            )
            return parsed

    # ── Error containment ────────────────────────────────────────────────

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
        note on city_options in options_adapter.
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