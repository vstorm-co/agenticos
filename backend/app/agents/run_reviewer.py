"""A second model that reads a run while it goes, and steers it (#2106).

Long runs drift: instructions fade, unsupported claims build on each other, the
agent wanders off the request. Guardrails check fixed boundaries and evaluation
scores a run after it ends, when the only fix is a re-run. A reviewer watches a
run while correcting it is still cheap.

The shape is `pydantic-ai-harness`'s `TrajectoryJudge` - every `every` requests a
second model reads the most recent `window` of the run and answers *on track* or
one short correction, delivered on the run's next request with the reviewer's
name on it - and the transcript it reads is rendered by the same function. What
differs is what a platform has to add to it:

- **Governed like any model call.** The review runs through
  :func:`~app.agents.capabilities._ambient.run_ambient_agent`: checked against the
  agent's and the organization's caps before it is made, booked on the run's
  ledger, traced the way the run is. A review refused for budget is skipped.
- **Never the run's failure.** The judge raises its failure on the run; a
  reviewer that cannot review is logged and the run goes on - a run must not be
  lost to the thing watching it.
- **Not refused under Prefect.** The judge rejects a run inside a durable flow,
  because its calls would repeat on replay. A routine or workflow here runs the
  agent inside a Prefect flow that does not replay a run's steps: a retry starts
  the run over, its own model calls with it, so a review there repeats exactly
  when the run's own requests do.
- **Written down.** Each correction is kept on the run's manifest with the
  reviewer's name, so the run history shows what steered the run and who sent it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import AbstractCapability, WrapRunHandler
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext
from pydantic_ai_harness.guardrails import GuardrailResult
from pydantic_ai_harness.trajectory_judge._capability import _judge_prompt

from app.agents.capabilities._ambient import AmbientCallSkipped, run_ambient_agent
from app.agents.capabilities.guardrails import GuardrailBlocked
from app.agents.deps import AgentDeps
from app.agents.manifest import MAX_RECORDED_REVIEWS, RunRecorder

if TYPE_CHECKING:
    from pydantic_ai.agent import AgentRunResult
    from pydantic_ai.models import ModelRequestContext

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "You review another AI agent's run while it is still going. You are shown the most "
    "recent part of it: the request, the agent's messages, its tool calls and what they "
    "returned. Judge it against your review focus. Answer on_track=true when the run is "
    "fine. Otherwise answer on_track=false with steer: one short, specific correction the "
    "agent can act on at once. A correction interrupts the agent, so send one only when it "
    "is worth that."
)


MAX_STEER_CHARS = 1_000
"""How long a correction may be. One or two sentences is what the reviewer is asked
for; a longer one is cut, so a verbose reviewer cannot fill the run's prompt."""


class ReviewVerdict(BaseModel):
    """What one review concludes."""

    on_track: bool
    steer: str | None = Field(
        default=None, description="The correction, when `on_track` is false. One or two sentences."
    )


@dataclass
class RunReviewer(AbstractCapability[AgentDeps]):
    """Reviews the run every `every` requests, and enqueues a correction when it drifts."""

    name: str
    model: Model
    instructions: str
    recorder: RunRecorder
    every: int = 10
    window: int = 20_000
    model_settings: ModelSettings | None = None
    screen: Callable[[str], GuardrailResult] | None = None
    """The agent's input guardrail, which a correction passes before the model reads it."""
    _steps: int = field(default=0, init=False, repr=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    async def after_model_request(
        self,
        ctx: RunContext[AgentDeps],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        """Count the request, and start a review when one is due and none is running.

        The transcript is rendered here, before the run moves on, and the review runs
        beside it: the run is not held up while a second model reads.
        """
        self._steps += 1
        if self._steps % self.every == 0 and (self._task is None or self._task.done()):
            prompt = _judge_prompt([*request_context.messages, response], self.window, ctx.run_id)
            # The request it reads up to, fixed now: by the time it answers the run
            # may have moved on.
            self._task = asyncio.create_task(
                self._review(ctx, prompt, self._steps), name=f"run-reviewer:{self.name}"
            )
        return response

    async def wrap_run(
        self, ctx: RunContext[AgentDeps], *, handler: WrapRunHandler
    ) -> AgentRunResult[Any]:
        """Run the agent, and cancel a review still going when it ends: it has nowhere to land."""
        try:
            return await handler()
        finally:
            if self._task is not None and not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

    async def _review(self, ctx: RunContext[AgentDeps], prompt: str, after_request: int) -> None:
        try:
            verdict = await run_ambient_agent(
                ctx,
                output_type=ReviewVerdict,
                user_prompt=prompt,
                instructions=f"{_INSTRUCTIONS}\n\nYour review focus:\n{self.instructions}",
                model=self.model,
                model_settings=self.model_settings,
            )
        except AmbientCallSkipped:
            logger.info("Run reviewer %s skipped a review: the run is at a budget cap", self.name)
            return
        except Exception:
            # A reviewer that cannot review costs the review, never the run.
            logger.exception("Run reviewer %s could not review the run", self.name)
            return
        if verdict.on_track or not verdict.steer:
            return
        steer = verdict.steer[:MAX_STEER_CHARS]
        if self.screen is not None:
            try:
                screened = self.screen(steer)
            except GuardrailBlocked:
                # A correction the guardrail refuses is dropped, never the run.
                logger.info(
                    "Run reviewer %s sent a correction the input guardrail refused", self.name
                )
                return
            if screened.action == "replace":
                steer = str(screened.replacement)
        ctx.enqueue(f"Steering from run reviewer {self.name!r}: {steer}")
        if len(self.recorder.reviews) < MAX_RECORDED_REVIEWS:
            self.recorder.reviews.append(
                {"reviewer": self.name, "after_request": after_request, "steer": steer}
            )
