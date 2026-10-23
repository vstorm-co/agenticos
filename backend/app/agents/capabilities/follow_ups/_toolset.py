"""The tools the follow-ups capability exposes.

The public methods below are the tools, and their docstrings are the only
description of them the model ever reads.
"""

import json
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai.tools import AgentDepsT, RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer

MAX_STEPS = 3
MAX_STEP_CHARS = 80
MAX_PROPOSALS = 3


class SetupProposal(BaseModel):
    """One thing to set up for the person, drawn as a card they act on in one click."""

    kind: Literal["agent", "routine", "connection"] = Field(
        description=(
            "`agent`: an assistant of their own, built with the Architect. `routine`: you, "
            "running a request on a schedule. `connection`: one of their services, connected "
            "with their own account."
        )
    )
    title: str = Field(max_length=80, description="The card's title, in their language.")
    why: str = Field(
        max_length=200, description="One sentence: what it would do for them, from what they said."
    )
    request: str = Field(
        max_length=2000,
        description=(
            "For an agent, what it should do; for a routine, its complete prompt; for a "
            "connection, the service's name as the MCP servers page lists it."
        ),
    )
    server: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "For a connection, the service's `key` as the MCP server search returned it - "
            "the card then shows its logo and connects it in one click; otherwise null."
        ),
    )
    cron: str | None = Field(
        default=None,
        max_length=60,
        description="For a routine, a UTC cron such as '0 7 * * 1-5'; otherwise null.",
    )


class FollowUpsToolset(FunctionToolset[AgentDepsT]):
    """Offers the person what to do next as buttons and cards rather than as a closing paragraph."""

    def __init__(self, *, offer_steps: bool = True) -> None:
        """`offer_steps` false leaves the next steps to a model of their own (#2301)."""
        super().__init__()
        if offer_steps:
            self.add_function(self.suggest_next_steps, name="suggest_next_steps")
        self.add_function(self.propose_setup, name="propose_setup")

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

    def propose_setup(self, ctx: RunContext[AgentDepsT], proposals: list[SetupProposal]) -> str:
        """Propose up to three concrete things to set up, as cards the person acts on in one click.

        Use it once you know what somebody does and what eats their time - at the
        end of a welcome interview, or when they ask how to get more out of this
        place. Make each proposal specific to what they told you - "A Monday
        digest of new support tickets", not "Try routines" - and mix the kinds
        where it fits: an agent of their own, a routine, a service to connect.
        The cards say what each does; do not repeat them in your answer.

        Use it too whenever what they want needs one of their services that is
        not connected - their mail, calendar, Notion, CRM: one `connection` card
        with the service's `server` key, which they connect without leaving the
        conversation, instead of a link to the MCP servers page.

        Args:
            proposals: One to three proposals.

        Returns:
            The proposals as shown, as JSON - nothing to repeat to the person.
        """
        if not proposals:
            return steer(ctx, "Give at least one proposal, or skip this tool.")
        if len(proposals) > MAX_PROPOSALS:
            return steer(ctx, f"Propose at most {MAX_PROPOSALS} things; keep the most useful.")
        return json.dumps(
            {"proposals": [proposal.model_dump() for proposal in proposals]}, ensure_ascii=False
        )
