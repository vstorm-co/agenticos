"""Setup cards; next-step generation belongs to the post-answer service."""

from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities.follow_ups._toolset import MAX_STEP_CHARS, MAX_STEPS, FollowUpsToolset
from app.agents.deps import AgentDeps

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


@dataclass
class FollowUps(AbstractCapability[AgentDeps]):
    """Keep setup cards available without asking the main model to write next steps."""

    _toolset: FollowUpsToolset[AgentDeps] | None = field(default=None, init=False, repr=False)

    def get_toolset(self) -> FollowUpsToolset[AgentDeps]:
        if self._toolset is None:
            self._toolset = FollowUpsToolset[AgentDeps]()
        return self._toolset

    def get_instructions(self) -> str:
        return (
            "Next-step buttons are generated separately after your answer is saved. "
            "Do not call suggest_next_steps, wait for suggestions, or repeat them in your answer. "
            "Answer the request directly. Setup proposal cards remain available through propose_setup."
        )
