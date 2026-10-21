"""The tool the follow-ups capability exposes.

The public method below is the tool, and its docstring is the only description
of it the model ever reads.
"""

import json

from pydantic_ai.tools import AgentDepsT, RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer

MAX_STEPS = 3
MAX_STEP_CHARS = 80


class FollowUpsToolset(FunctionToolset[AgentDepsT]):
    """Offers the person the next steps as buttons rather than as a closing paragraph."""

    def __init__(self) -> None:
        super().__init__()
        self.add_function(self.suggest_next_steps, name="suggest_next_steps")

    def suggest_next_steps(self, ctx: RunContext[AgentDepsT], steps: list[str]) -> str:
        """Offer up to three next steps as buttons under your answer.

        Call it last, after the answer is written, when there is a natural next
        step - a follow-up question, turning the result into something they can
        keep, doing it again on a schedule. Each step is what the person would
        say to you, in their language and first person, short enough for a
        button: "Make it a table", "Do this every Monday at 9:00", "Explain the
        second point". Clicking one sends it as their next message, so do not
        also list the steps in your answer. Skip it after small talk, a question
        you asked them, or when nothing useful follows.

        Args:
            steps: One to three next steps, each at most 80 characters.

        Returns:
            The steps as shown, as JSON - nothing to repeat to the person.
        """
        cleaned = [step.strip() for step in steps if step.strip()]
        if not cleaned:
            return steer(ctx, "Give at least one next step, or skip this tool.")
        if len(cleaned) > MAX_STEPS:
            return steer(ctx, f"Offer at most {MAX_STEPS} next steps; keep the most useful.")
        if too_long := [step for step in cleaned if len(step) > MAX_STEP_CHARS]:
            return steer(
                ctx,
                f"Each step must fit a button - at most {MAX_STEP_CHARS} characters. "
                f"Shorten: {too_long[0]!r}",
            )
        return json.dumps({"steps": cleaned}, ensure_ascii=False)
