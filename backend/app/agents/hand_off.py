"""A call's text twin: what the realtime model hands work to (#54).

A realtime session cannot carry a workspace, a browser or delegates
(`app/agents/voice.py`), and an agent whose work needs them is still the agent
somebody calls. So the call's model gets one tool, `hand_off`, which runs the
same spec on the agent's own text model - the one its Build tab names - in the
run's workspace, under the run's budget, and answers with what it did; the
call's model says it aloud. Every step the twin takes is handed to `watch`, so
the call shows it while it runs and saves it on the turn, as a chat would.

One twin per call, built the first time it is needed, and its hand-offs run one
at a time: each continues from what the previous one did, so a call can say
"now send that file" after "write it up".
"""

import logging
from collections.abc import AsyncIterable, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import anyio
from pydantic_ai.exceptions import AgentRunError, ToolFailed, UsageLimitExceeded
from pydantic_ai.messages import AgentStreamEvent, ModelMessage
from pydantic_ai.tools import DeferredToolRequests, RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.workspaces import Workspace

from app.agents.capabilities.budget import BudgetExceeded, SpendShare, booked_to
from app.agents.deps import AgentDeps
from app.agents.factory import BuiltAgent
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

HAND_OFF_TOOL = "hand_off"

HAND_OFF_DESCRIPTION = (
    "Hand a task to yourself working in text, where you have what this call does not: {tools}. "
    "Use it for anything that needs those. Describe the task completely, with every name, number, "
    "address and detail the person gave, because the text side cannot hear this call. It can take "
    "a minute or more: tell the person you are working on it before you call this, and say what it "
    "answers when it does."
)
"""The tool the call's model is given. `{tools}` names the capabilities handed off."""

WORKER_STYLE = """This task was handed to you from a live voice call, by the voice that is speaking with the person. What you answer goes back to that voice, which says it aloud.
- Do the task with your tools, then say in a few plain sentences what you did and what you found.
- No markdown, lists, tables, links or code in the answer: say what they mean. Name a file you wrote by its name.
- If you cannot go on without something from the person, stop and say exactly what you need."""
"""The twin's instructions for one hand-off, on top of the agent's own."""

HAND_OFF_FAILED = (
    "The work did not finish: {reason}. Tell the person plainly that it did not get done, and do "
    "not say that any part of it did."
)

WorkerEvents = Callable[[AgentStreamEvent], Awaitable[None]]
"""Where the twin's events go while it works: the call's event pump."""


@dataclass(frozen=True)
class HandOffSpend:
    """What one hand-off spent on the text model, for its own row.

    The twin shares the call's ledger and guard, so its money is on the call's
    run either way; a row of its own puts that money under the text model's
    provider and key rather than the realtime key's, as a delegation's row does.
    """

    task_id: str
    share: SpendShare
    started_at: datetime
    ended_at: datetime
    error: str | None


HandOffReport = Callable[[HandOffSpend], None]


class CallWorker:
    """The text twin of one call's agent, and the `hand_off` tool that reaches it.

    `build` makes the twin with nothing left to look up - the runner resolved the
    model, the tools, the secrets and the delegates before the call connected - so
    building it from inside a tool call is CPU work only, as a delegate's is.
    """

    def __init__(
        self,
        build: Callable[[], BuiltAgent],
        *,
        workspace: Workspace | None,
        capability_names: Sequence[str],
        report: HandOffReport | None = None,
    ) -> None:
        self._build = build
        self._workspace = workspace
        self._names = capability_names
        self._report = report
        self._built: BuiltAgent | None = None
        self._history: list[ModelMessage] = []
        self._lock = anyio.Lock()
        self.watch: WorkerEvents | None = None

    def toolset(self) -> FunctionToolset[AgentDeps]:
        """The call's one way to the twin."""
        toolset = FunctionToolset[AgentDeps]()
        toolset.add_function(
            self.hand_off,
            name=HAND_OFF_TOOL,
            description=HAND_OFF_DESCRIPTION.format(tools=", ".join(self._names)),
        )
        return toolset

    async def hand_off(self, ctx: RunContext[AgentDeps], task: str) -> str:
        """Run `task` on the twin and answer with what it said.

        Raises:
            ToolFailed: When the twin could not finish - out of budget, out of
                steps, a model that failed - with a sentence the call's model
                says rather than an error that ends the call.
        """
        async with self._lock:
            if self._built is None:
                self._built = self._build()
            built = self._built
            # The call's question card, which the twin's `ask_user` reaches and
            # which its delegates inherit from these deps.
            built.deps.ask_questions = ctx.deps.ask_questions
            # The same provenance set, not a copy: a clip the twin makes may start
            # from an image the call drew, and what the twin makes is the call's.
            built.deps.generated_files = ctx.deps.generated_files
            task_id = f"hand-off-{uuid4().hex[:12]}"
            started_at = datetime.now(UTC)
            error: str | None = None
            try:
                with booked_to(task_id, has_own_row=True):
                    result = await built.agent.run(
                        task,
                        instructions=WORKER_STYLE,
                        deps=built.deps,
                        message_history=self._history,
                        usage_limits=built.usage_limits,
                        workspace=self._workspace,
                        event_stream_handler=self._forward,
                    )
                if isinstance(result.output, DeferredToolRequests):
                    # Approvals and questions are settled inline in a call, so only
                    # a deferral nothing here can answer is left. Inside the `try`,
                    # so the hand-off's row records it as failed.
                    error = "it stopped to wait for something a call cannot give it"
                    raise ToolFailed(HAND_OFF_FAILED.format(reason=error))
            except (AgentRunError, AppException, BudgetExceeded) as exc:
                logger.exception("voice_hand_off_failed")
                error = _reason(exc)
                raise ToolFailed(HAND_OFF_FAILED.format(reason=error)) from exc
            finally:
                if self._report is not None:
                    self._report(
                        HandOffSpend(
                            task_id=task_id,
                            share=built.budget.ledger.billed_share_of(task_id),
                            started_at=started_at,
                            ended_at=datetime.now(UTC),
                            error=error,
                        )
                    )
            self._history = result.all_messages()
            return result.output

    async def _forward(
        self, _ctx: RunContext[AgentDeps], events: AsyncIterable[AgentStreamEvent]
    ) -> None:
        async for event in events:
            if self.watch is not None:
                await self.watch(event)


def _reason(exc: Exception) -> str:
    if isinstance(exc, BudgetExceeded):
        return "there is no budget left for it"
    if isinstance(exc, UsageLimitExceeded):
        return "it took more steps than this agent is allowed"
    return "it failed partway"
