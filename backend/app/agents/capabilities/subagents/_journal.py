"""What one run has delegated: how many are in flight, and what each one cost.

Three questions have to be answered in one place, because all three are about
the *set* of delegations a run has started rather than about any single one:

*How many are running?* `max_fanout` is a ceiling on concurrency, and a
delegation is in flight from the tool call that starts it until its task reaches
a terminal status - which, for a background delegation, is long after the call
returned.

*What did this one cost?* A delegate records into the parent run's ledger by
construction (that is what makes the parent's budget see a delegate's spend
before the next request), so the only number that describes one delegation is
what the shared total grew by while it ran. Exact for a sync delegation, which
holds the parent's run loop; approximate for concurrent ones, whose windows
overlap - stated in :class:`app.agents.subagent_runtime.DelegationOutcome` rather
than hidden here.

*Which delegation is this event from?* The library resolves an event-stream
handler once per delegation and hands it the task id, which is the only place
that id is available *before* the delegation runs. That is why `stream_for` is
here and why it hands the id back through a context variable: the tool call that
started the delegation needs it to record the outcome, and the library never
returns it for a sync task.

Nothing in this module reads the database or knows what a run row is. It reports
a finished delegation to `SubagentRuntime.record`, which the runner supplied, and
a `None` recorder is not an error - it is a preview, or a test.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic_ai.agent import EventStreamHandler
from pydantic_ai.messages import AgentStreamEvent
from pydantic_ai.tools import RunContext
from subagents_pydantic_ai import (
    SubAgentConfig,
    TaskCharacteristics,
    TaskHandle,
    TaskManager,
    TaskStatus,
    decide_execution_mode,
)

from app.agents.capabilities.subagents._events import FrameLabels, frame_for
from app.agents.deps import AgentDeps
from app.agents.spec import DelegationMode
from app.agents.subagent_events import SubagentEventSink, SubagentFinished, SubagentStarted
from app.agents.subagent_runtime import (
    DelegationOutcome,
    DelegationStatus,
    ResolvedSubagent,
    SubagentRuntime,
)

_RESOLVED: dict[TaskStatus, DelegationStatus] = {
    TaskStatus.COMPLETED: "completed",
    TaskStatus.FAILED: "failed",
    TaskStatus.CANCELLED: "cancelled",
}
"""The library's terminal statuses, as this platform records them.

`DEFERRED` is deliberately absent, and :func:`_terminal_status` decides it per
delegation instead - because it means two different things depending on the mode.
"""


def _terminal_status(handle: TaskHandle, mode: Literal["sync", "async"]) -> DelegationStatus | None:
    """How this platform records a delegation that reached `handle.status`.

    `None` means "not over": the task is still running, or it suspended in a way
    that is not an outcome to record.

    `DEFERRED` is the whole reason this is a function. It is terminal to the
    library, but it means two different things:

    *A sync delegation* suspended on a tool that needs a person, and the answer is
    still coming - the signal propagates into the parent's own tool call, so the
    parent run parks in the approval queue and resumes from there with the
    delegation re-run. Recording it would write a run row for work that has not
    finished, tell whoever reads it to look for a defect instead of for the
    queue, and then double-count the same work when the resumed run delegates
    again.

    *A background delegation* cannot suspend at all: the tool call that started it
    returned a task id long ago, so there is no caller left to hand a parked call
    back to, and the library says so on the handle - `handle.error` names the rule
    and tells the model to re-delegate with `mode="sync"`. That is a delegation
    that spent money and delivered nothing, which is `failed`. Reading it as
    "still going" is what the platform did until this function existed, and it
    failed in three ways at once: the spend was attributed to nothing, the
    fan-out slot was never released, and the panel a surface had opened never
    closed - none of which looks like an error anywhere.
    """
    if handle.status is TaskStatus.DEFERRED:
        return "failed" if mode == "async" else None
    return _RESOLVED.get(handle.status)


_NO_PREFERENCE: SubAgentConfig = SubAgentConfig(name="auto", description="", instructions="")
"""A config carrying no mode preference, for the one library call that wants one.

`decide_execution_mode` consults the config's `preferred_mode` before it looks at
the task - and this capability has already applied the delegate's preference by
the time it asks. Handing over the real config would apply it twice, which is
only harmless while the two agree.
"""

_CURRENT: ContextVar[Delegation | None] = ContextVar("current_delegation", default=None)
"""The delegation whose tool call is executing in this task.

A context variable rather than a field because the value is per delegation and
the toolset is per run: a fan-out of three runs three tool calls in three
asyncio tasks, each with its own copy of the context, so each sees its own. A
field would be whichever one wrote last.
"""


@dataclass(frozen=True)
class _Totals:
    """A run ledger's accumulated spend at one instant."""

    cost_usd: Decimal = Decimal(0)
    input_tokens: int = 0
    output_tokens: int = 0

    def since(self, before: _Totals) -> _Totals:
        """What the ledger grew by between `before` and this reading."""
        return _Totals(
            cost_usd=self.cost_usd - before.cost_usd,
            input_tokens=self.input_tokens - before.input_tokens,
            output_tokens=self.output_tokens - before.output_tokens,
        )


@dataclass
class Delegation:
    """One delegation, from the tool call that opened it to the outcome recorded for it.

    `task_id` is the handoff: it is `None` until the library resolves this
    delegation's event-stream handler, and it stays `None` when the library
    refused the delegation before starting one - an unknown delegate name, for
    instance. Nothing is recorded and nothing is streamed in that case, which is
    correct: no delegate ran.
    """

    name: str
    prompt: str
    mode: Literal["sync", "async"]
    depth: int
    before: _Totals
    agent_id: UUID | None = None
    agent_version_id: UUID | None = None
    task_id: str | None = None
    started: bool = False

    async def ensure_started(self, task_id: str, sink: SubagentEventSink) -> None:
        """Announce this delegation, at most once.

        Called both from the stream - where the first event is the earliest
        honest moment to say a delegate is working - and from the settlement,
        so a delegation that produced no events at all still opens its panel
        before closing it. A `subagent_complete` for a panel that was never
        opened is a delegation a reader never learns about.
        """
        if self.started:
            return
        self.started = True
        await sink(
            SubagentStarted(
                task_id=task_id,
                subagent=self.name,
                depth=self.depth,
                mode=self.mode,
                prompt=self.prompt,
            )
        )


@dataclass
class DelegationJournal:
    """The delegation bookkeeping for one run.

    Held by the capability, which this platform builds once per run, and shared
    by reference with the toolset - so a wrapper that Pydantic AI recreates
    between run steps keeps the same journal rather than starting a fresh count.
    """

    runtime: SubagentRuntime
    mode: DelegationMode
    max_fanout: int
    depth: int

    tasks: TaskManager = field(init=False, repr=False)
    """The library's task manager, assigned once the library capability exists.

    Late-bound for the same reason `SubagentRuntime.ledger` is: it is created
    inside the capability this journal is passed *into*, so no ordering exists in
    which the constructor could take it. `build_delegation` assigns it on the
    next line.
    """

    _running: int = field(default=0, init=False)
    _background: dict[str, Delegation] = field(default_factory=dict, init=False)

    def in_background(self) -> bool:
        """Whether the delegation executing in this task was started in the background.

        Read from the same context variable `stream_for` resolves a delegation
        through, and it reaches a background delegate for a reason worth stating:
        `asyncio.create_task` copies the current context, and the library creates
        the task inside the `delegating` block - so the whole of a background
        delegation, including its own tool calls, runs with its own `Delegation`
        visible here.

        What consults it is `_LazyAgent._own_deps`, which has to know before the
        delegate's first request. A background delegation is the only kind that
        must not be handed the parent's approval channel: the tool call that
        started it has returned, so nothing is left to park, and asking would
        write an approval row on a session the parent is still using.
        """
        delegation = _CURRENT.get()
        return delegation is not None and delegation.mode == "async"

    def in_flight(self) -> int:
        """How many delegations this run has going right now.

        Counts background delegations, which is the half that matters: a sync
        delegation holds the run loop and cannot outnumber the model's own
        parallel tool calls, while a run can launch background tasks and keep
        going until it has ten agents running against one budget.
        """
        return self._running + len(self._background)

    def refusal(self) -> str:
        """What the model is told when it asks for one delegation too many.

        A tool result rather than an exception. The model can act on this - wait,
        or do the work itself - and a raise would end the run over a limit that
        is a pacing decision, not a fault.
        """
        return (
            f"Refused: this agent may run {self.max_fanout} delegations at a time and that "
            "many are already running. Wait for one to finish (check_task, wait_tasks) and "
            "ask again, or do this part of the work yourself."
        )

    def begin(
        self,
        *,
        delegate: ResolvedSubagent | None,
        name: str,
        prompt: str,
        tool_args: dict[str, Any],
    ) -> Delegation:
        """Open a delegation, deciding the one thing the model does not get to.

        `delegate` is `None` when the model addressed something this runtime did
        not resolve - the library's general-purpose subagent, or a name it
        invented. Either way the mode falls back to the spec's, and a name
        nobody resolved is refused by the library a moment later.
        """
        self._running += 1
        return Delegation(
            name=name,
            prompt=prompt,
            mode=self._mode_for(delegate, tool_args),
            depth=self.depth,
            before=self._totals(),
            agent_id=delegate.agent_id if delegate is not None else None,
            agent_version_id=delegate.agent_version_id if delegate is not None else None,
        )

    async def close(self, delegation: Delegation, sink: SubagentEventSink | None) -> None:
        """Settle a delegation whose tool call has returned, or start watching it.

        A sync delegation is finished by the time its call returns, so this is
        where nearly every outcome is recorded - with an exact ledger delta,
        because nothing else in the run could have spent while the loop was
        blocked here. A background one is not: it is kept until its task reaches
        a terminal status, which `settle_background` looks for.
        """
        self._running -= 1
        task_id = delegation.task_id
        if task_id is None:
            return
        if not await self.settle(task_id, delegation, sink):
            self._background[task_id] = delegation

    async def settle_background(self, sink: SubagentEventSink | None) -> None:
        """Record every background delegation that has finished since the last look.

        Polled rather than pushed, at the two moments the answer is needed: before
        a fan-out check, so a finished task stops occupying a slot, and after the
        run, where the library has already cancelled and awaited whatever was
        still running.
        """
        for task_id, delegation in list(self._background.items()):
            if await self.settle(task_id, delegation, sink):
                del self._background[task_id]

    async def settle(
        self, task_id: str, delegation: Delegation, sink: SubagentEventSink | None
    ) -> bool:
        """Record one delegation if it has ended, answering whether it had.

        `False` means "still going": either the task is running, or it suspended
        on something needing a person, which is not an outcome to record.
        """
        handle = self.tasks.get_handle(task_id)
        if handle is None:
            # The library refused this delegation after resolving its handler but
            # before starting a task - a `chat_trace_id` it does not know. There
            # is no run to attribute anything to, and nothing to keep watching.
            return True
        status = _terminal_status(handle, delegation.mode)
        if status is None:
            return False

        delta = self._totals().since(delegation.before)
        run_id = await self._record(
            DelegationOutcome(
                subagent=delegation.name,
                task_id=task_id,
                status=status,
                cost_usd=delta.cost_usd,
                input_tokens=delta.input_tokens,
                output_tokens=delta.output_tokens,
                agent_id=delegation.agent_id,
                agent_version_id=delegation.agent_version_id,
                error=handle.error,
            )
        )
        if sink is not None:
            await delegation.ensure_started(task_id, sink)
            await sink(
                SubagentFinished(
                    task_id=task_id,
                    subagent=delegation.name,
                    depth=delegation.depth,
                    status=status,
                    run_id=run_id,
                    cost_usd=delta.cost_usd,
                    input_tokens=delta.input_tokens,
                    output_tokens=delta.output_tokens,
                    error=handle.error,
                )
            )
        return True

    def stream_for(
        self, ctx: RunContext[AgentDeps], config: SubAgentConfig, task_id: str
    ) -> EventStreamHandler[AgentDeps] | None:
        """The event-stream handler for one delegation, labelled with its own task id.

        The library calls this once per delegation, synchronously, inside the tool
        call that started it - which is what makes it the place the task id
        becomes known to this platform at all. Stamping it on the delegation is
        therefore not a side effect of streaming: the recording path needs it too,
        and a delegation whose events nobody wants still has to be recorded.

        Returns `None` - no streaming - when there is no sink on this run's deps,
        and when the delegation was started by something this capability does not
        intercept. Unlabelled frames are worse than none: a surface cannot tell
        whose panel they belong to.
        """
        delegation = _CURRENT.get()
        if delegation is None:
            return None
        delegation.task_id = task_id
        sink = ctx.deps.subagent_events
        if sink is None:
            return None
        labels = FrameLabels(task_id=task_id, subagent=delegation.name, depth=delegation.depth)

        async def stream(
            _ctx: RunContext[AgentDeps], events: AsyncIterable[AgentStreamEvent]
        ) -> None:
            await delegation.ensure_started(task_id, sink)
            async for event in events:
                frame = frame_for(event, labels)
                if frame is not None:
                    await sink(frame)

        return stream

    @contextmanager
    def delegating(self, delegation: Delegation) -> Iterator[None]:
        """Make `delegation` the one the library's handler factory will find.

        A context manager so the variable is reset on the way out however the
        delegation ended: a leaked value would attach the next delegation's task
        id to this record, and the panel would then narrate the wrong specialist.
        """
        token = _CURRENT.set(delegation)
        try:
            yield
        finally:
            _CURRENT.reset(token)

    def _mode_for(
        self, delegate: ResolvedSubagent | None, tool_args: dict[str, Any]
    ) -> Literal["sync", "async"]:
        """Whether this delegation blocks the parent or runs in the background.

        The spec decides, not the model. The library's `task` tool takes a `mode`
        argument defaulting to `"sync"`, so "the model chose sync" and "the model
        said nothing" are the same value - there is no way to honour both an
        author's setting and a model's choice, and the author's is the one that
        was reviewed. An author who wants the model to decide sets `auto`.

        `auto` is resolved here rather than left to the library, because
        `SubagentStarted.mode` has to be a concrete answer *before* the
        delegation runs: it is what tells a surface whether to keep the panel
        open after the parent has answered.
        """
        preferred = delegate.preferred_mode if delegate is not None else None
        wanted = preferred or self.mode
        if wanted != "auto":
            return wanted
        return decide_execution_mode(_characteristics(tool_args), _NO_PREFERENCE)

    async def _record(self, outcome: DelegationOutcome) -> UUID | None:
        """Hand a finished delegation to the runner, if there is one listening."""
        if self.runtime.record is None:
            return None
        return await self.runtime.record(outcome)

    def _totals(self) -> _Totals:
        """The run ledger's totals now, or zeros when nothing is metering.

        A `None` ledger is a preview or a test, and zero is the honest answer
        there - reporting a cost nobody measured would be worse than reporting
        none.
        """
        ledger = self.runtime.ledger
        if ledger is None:
            return _Totals()
        return _Totals(
            cost_usd=ledger.total_usd,
            input_tokens=ledger.input_tokens,
            output_tokens=ledger.output_tokens,
        )


def _characteristics(tool_args: dict[str, Any]) -> TaskCharacteristics:
    """The task properties the model reported, as the library's auto mode reads them."""
    return TaskCharacteristics(
        estimated_complexity=tool_args.get("complexity") or "moderate",
        requires_user_context=bool(tool_args.get("requires_user_context")),
        may_need_clarification=bool(tool_args.get("may_need_clarification")),
    )
