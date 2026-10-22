"""Next steps the person can take with one click."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.tools import RunContext

from app.agents.capabilities._ambient import AmbientCallSkipped, run_ambient_agent
from app.agents.capabilities.follow_ups._toolset import (
    MAX_STEP_CHARS,
    MAX_STEPS,
    FollowUpsToolset,
)
from app.agents.deps import AgentDeps, WrittenNextSteps

if TYPE_CHECKING:
    from pydantic_ai.models import ModelRequestContext

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "You read a person's request to an AI agent and the agent's answer, and offer the "
    f"person up to {MAX_STEPS} next steps they are likely to want - a follow-up question, "
    "turning the result into something they can keep, doing it again on a schedule. Write "
    "each step as the person would say it to the agent, in the language of their request "
    f"and in the first person, short enough for a button: at most {MAX_STEP_CHARS} "
    'characters, such as "Make it a table" or "Do this every Monday at 9:00". Offer none '
    "after small talk, after an answer that asks the person a question, or when nothing "
    "useful follows."
)

_SHOWN_CHARS = 6_000
"""How much of the request and of the answer the step writer reads: enough to know
what was asked and what came back, and a cap on what a long answer costs."""


class _Steps(BaseModel):
    steps: list[str] = Field(default_factory=list, description="Zero to three next steps.")


def kept_steps(steps: list[str]) -> list[str]:
    """The steps a button can carry: blank and over-long ones dropped, three at most."""
    cleaned = [step.strip() for step in steps]
    return [step for step in cleaned if step and len(step) <= MAX_STEP_CHARS][:MAX_STEPS]


def _request_of(messages: Sequence[ModelMessage]) -> str:
    """The person's latest request in the run's messages, as text."""
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    return ""


@dataclass
class FollowUps(AbstractCapability[AgentDeps]):
    """Lets an agent end a turn with buttons for what to do next (#2301).

    A paragraph of "Would you like me to..." at the end of every answer is the
    habit people complain about most, and a newcomer who does not know what to
    ask next reads straight past it. As buttons the same suggestions cost one
    click, and the answer above them stays the answer.

    With `model` set the agent is not offered `suggest_next_steps`: once its
    answer is in, that model reads the request and the answer and writes the
    steps - a small model doing a small job, rather than the agent's own spending
    a request on it. The call is governed and booked like any of the run's.

    ```python
    from pydantic_ai import Agent
    from app.agents.capabilities.follow_ups import FollowUps

    agent = Agent('openai:gpt-4.1', capabilities=[FollowUps()])
    ```
    """

    model: Model | None = None
    _toolset: FollowUpsToolset[AgentDeps] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> FollowUpsToolset[AgentDeps]:
        """The follow-ups toolset, built once per capability instance."""
        if self._toolset is None:
            self._toolset = FollowUpsToolset[AgentDeps](offer_steps=self.model is None)
        return self._toolset

    async def after_model_request(
        self,
        ctx: RunContext[AgentDeps],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        """Write the next steps once the answer that ends the turn is in."""
        if self.model is None or any(isinstance(part, ToolCallPart) for part in response.parts):
            return response
        answer = response.text or ""
        if not answer.strip():
            return response
        request = _request_of(request_context.messages)
        try:
            written = await run_ambient_agent(
                ctx,
                output_type=_Steps,
                user_prompt=(
                    f"The request:\n{request[:_SHOWN_CHARS]}\n\n"
                    f"The agent's answer:\n{answer[:_SHOWN_CHARS]}"
                ),
                instructions=_INSTRUCTIONS,
                model=self.model,
            )
        except AmbientCallSkipped:
            logger.info("Next steps not written: the run is at a budget cap")
            return response
        except Exception:
            # Steps that could not be written cost the buttons, never the answer.
            logger.exception("Could not write the next steps")
            return response
        steps = kept_steps(written.steps)
        ctx.deps.next_steps = (
            WrittenNextSteps(call_id=f"next_steps_{uuid.uuid4().hex[:12]}", steps=steps)
            if steps
            else None
        )
        return response
