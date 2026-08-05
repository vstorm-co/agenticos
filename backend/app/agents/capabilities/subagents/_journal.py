"""What one run has delegated: how many are in flight, and what each one cost.

Three questions have to be answered in one place, because all three are about
the *set* of delegations a run has started rather than about any single one:

*How many are running?* `max_fanout` is a ceiling on concurrency, and a
delegation is in flight from the tool call that starts it until its task reaches
a terminal status - which, for a background delegation, is long after the call
returned.

*What did this one cost?* A delegate records into the parent run's ledger by
construction - that is what makes the parent's budget see a delegate's spend
before the next request - so what describes one delegation is the part of that
ledger its own requests booked. `delegating` names the delegation while it runs
and the ledger stamps every entry with the name, so the answer is read back rather
than inferred from when anyone happened to look.

That measurement used to be a *delta*: the total when the delegation opened
subtracted from the total when it was settled. It was wrong twice, and both were
silent (agenticos#180). A background delegation is settled when it is next polled,
so everything the parent spent in between landed on the child - a delegate that
spent $0.01 was recorded at $0.51 if the parent then spent $0.50. And a mid-tree
delegate's window contained what its own delegates spent, which their own rows
record again, so its monthly total counted its grandchildren.

*Which delegation is this event from?* The library resolves an event-stream
handler once per delegation and hands it the task id, which is the only place
that id is available *before* the delegation runs. That is why `stream_for` is
here and why it hands the id back through a context variable: the tool call that
started the delegation needs it to record the outcome, and the library never
returns it for a sync task.

*Where did this delegation stop, and how is it continued?* A delegate whose tool
needs a person parks the whole run, and the run is picked up in another process,
possibly the next day. What has to survive is the delegate's own conversation, the
call it stopped on, and **what it had already spent** - `park` writes all three
into the run's stash and `resuming` reads the first two back on the replay. Both
are here rather than in the toolset because the delegation record and the
library's task handle are both fields of this object.

The spend is the half that is easy to lose, because losing it breaks nothing.
Each turn measures against its own ledger, so a delegation settled after a resume
reported only what it spent *after* the resume - and on a delegate that did the
work and then asked permission to act on it, that is the small half. The child
`AgentRun` row, the delegate's monthly total and any budget alert on it were all
short by the same amount, while the parent's row still held the whole cost, so no
total anywhere disagreed with another. `Delegation.carried` is what the resume
puts back, and `_spent` is the one place the segments are added.

Nothing in this module reads the database or knows what a run row is. It reports
a finished delegation to `SubagentRuntime.record`, which the runner supplied, and
a `None` recorder is not an error - it is a preview, or a test.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID, uuid4

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

from app.agents.capabilities.budget import SpendShare, booked_to
from app.agents.capabilities.subagents._events import FrameLabels, frame_for
from app.agents.deps import AgentDeps
from app.agents.spec import DelegationMode
from app.agents.subagent_events import SubagentEventSink, SubagentFinished, SubagentStarted
from app.agents.subagent_runtime import (
    DelegationOutcome,
    DelegationSpend,
    DelegationStatus,
    ParkedDelegation,
    ResolvedSubagent,
    ResumedDelegation,
    SubagentRuntime,
)

logger = logging.getLogger(__name__)

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
    parent run parks in the approval queue and is continued from there, this
    delegate included (:meth:`DelegationJournal.park`). Recording it would write a
    run row for work that has not finished, tell whoever reads it to look for a
    defect instead of for the queue, and then count the same delegation twice,
    because the continuation records one of its own when it answers.

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
class ActingDelegate:
    """Which delegate is running in this asyncio task, for a caller outside the run.

    One reader, and it is the approval queue. A delegate's gated tool reaches the
    *parent's* approval channel - that is what makes a gated tool inside a
    delegate usable at all - so the row that channel writes says `send_email`
    without saying who is sending it. A reviewer looking at a queue of tool names
    with no actor is a reviewer approving blind.

    Read from a context variable rather than passed through
    `app.agents.approval.ApprovalRequest`, because the gate that builds that
    request has no way to know: it wraps tool execution on whatever agent it was
    built for, and a delegate is a whole second agent run away from the one that
    owns the channel.
    """

    name: str
    task_id: str | None
    agent_id: UUID | None


def acting_delegate() -> ActingDelegate | None:
    """The delegate whose run is executing here, or `None` for the run's own agent.

    The innermost one: a specialist's own specialist sets the variable again, so a
    grandchild's gated call is attributed to the grandchild rather than to
    whichever delegate the parent addressed.

    Visible from inside a delegate's tool call because `contextvars` are copied
    into every task a delegation spawns, and the value is set around the tool call
    that starts one. A background delegation is never a reader: it is handed no
    approval channel at all, for the reason `in_background` gives.
    """
    delegation = _CURRENT.get()
    if delegation is None:
        return None
    return ActingDelegate(
        name=delegation.name, task_id=delegation.task_id, agent_id=delegation.agent_id
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
    ledger_key: str
    """What the run's ledger stamps on the requests this delegation makes.

    This platform's own id for the delegation, allocated when it opens, rather than
    the library's `task_id`: the attribution has to be in place *before* the tool
    call that starts the delegation, and no task id exists until the library
    resolves this delegation's event-stream handler inside that call. It is also
    the only handle a delegation the library refuses outright ever gets.

    Not a display value and never shown to anyone - `task_id` is what a surface,
    a run row and a streamed frame all carry.
    """

    tool_call_id: str | None
    """The `task` call in the delegating agent's transcript that opened this.

    What identifies the delegation across a park and a resume: the replayed run
    presents the same call, which is how the toolset knows to continue a delegate
    rather than start one. `None` only where a caller drives the toolset without a
    tool call to name, which is a test.
    """

    parent_task_id: str | None
    """The delegation this one was made inside, or `None` for the run's own agent.

    Read when the delegation opens rather than when it parks: by then this
    delegation is the current one, and the enclosing delegation - the one whose
    tool call this toolset is executing inside - is no longer visible.
    """

    carried: DelegationSpend
    """What this delegation spent before the turn that parked it ended.

    Zero for a delegation this run started, which is all of them until one parks.
    Non-zero only on a replay, where :attr:`ledger_key` is freshly allocated against
    a ledger this turn built empty - so the share read back describes the
    continuation and nothing before it. :meth:`_spent` adds the two.
    """

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
                # The delegation this one was made inside, so a surface nests the
                # panel instead of guessing which one it belongs under. `None` for
                # a delegation the run's own agent started.
                parent_task_id=self.parent_task_id,
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

        No delegation in flight answers `False`, which is the same answer a sync
        one gets. That is only reachable through an entry point this capability
        does not intercept, and such a delegation has already escaped the mode,
        the fan-out ceiling and the recording - so a defensive branch here would
        guard the smallest of four holes that all close the same way, by routing
        the entry point through `_toolset.py`.
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
        tool_call_id: str | None,
    ) -> Delegation:
        """Open a delegation, deciding the one thing the model does not get to.

        `delegate` is `None` when the model addressed something this runtime did
        not resolve - a specialist it invented, or a name it invented outright.
        Either way the mode falls back to the spec's, and a name nobody resolved
        is refused by the library a moment later.

        The enclosing delegation is read here, before this one becomes the current
        value, because that is the only moment both exist: from inside
        :meth:`delegating` a nested level can no longer see the level it was
        delegated from, and that relationship is what nests a parked tree.

        A delegation the run is *continuing* opens here too - the replay presents
        the same `task` call - which is why what it already spent is read here as
        well. The ledger key allocated here is fresh, and this turn's ledger has
        never held an entry under any other, so without `carried` the continuation
        would be the whole of the delegation's recorded cost.
        """
        self._running += 1
        enclosing = _CURRENT.get()
        return Delegation(
            name=name,
            prompt=prompt,
            mode=self._mode_for(delegate, tool_args),
            depth=self.depth,
            ledger_key=uuid4().hex,
            tool_call_id=tool_call_id,
            parent_task_id=None if enclosing is None else enclosing.task_id,
            carried=self.runtime.stash.already_spent(tool_call_id),
            agent_id=delegate.agent_id if delegate is not None else None,
            agent_version_id=delegate.agent_version_id if delegate is not None else None,
        )

    def park(self, delegation: Delegation) -> None:
        """Keep a suspended delegate's place, so the resume continues it.

        Called where the suspension propagates out of the delegation - the parent's
        own `task` call is about to park too - and it is the only moment the
        delegate's conversation is reachable: the library saves a message history
        on the task handle when it records the suspension, and deliberately does
        *not* save it as a chat trace, because a trace resumed from a point whose
        deferred results were never supplied would replay the suspension forever.

        Without this the parent simply delegates again on the resume. That is not
        a slow path, it is a wrong answer: the approval a person granted names the
        delegate's tool call, the replayed parent presents its own `task` call, and
        the delegate starts from nothing with the model free to call something
        else. What a reviewer approved is not what executes, and nothing raises.

        Two states are recorded rather than one, and the difference matters:

        *A delegation with a task id and a saved history* is continued from where
        it stopped.

        *A delegation with a task id and no history* is stashed anyway, with no
        messages. Telemetry on the handle is best-effort upstream, so this is
        reachable, and the frame is still worth writing: the `task` call has to be
        answered on the replay or Pydantic AI refuses the whole resume as
        incomplete. The delegation is then re-run from the start - the old
        behaviour, for a case that used to be the only one.

        *A delegation with no task id at all* stashes nothing. The library assigns
        one before it runs anything, so no delegate can have suspended; a
        suspension arriving here without one came from something that is not a
        delegate, and inventing a frame for it would claim the run's own parked
        calls as a delegate's.

        What the delegation has spent is written whichever of the first two states
        it is in, and it is not the same number as this turn's share of the ledger:
        a delegation on its second park carries the first park's total as well. So
        the frame holds a running sum, and the turn that finally settles the
        delegation records one row for all of it - see :meth:`_spent`.
        """
        task_id = delegation.task_id
        if task_id is None or delegation.tool_call_id is None:
            logger.warning(
                "delegation_suspended_before_it_started",
                extra={"subagent": delegation.name, "task_id": task_id},
            )
            return
        handle = self.tasks.get_handle(task_id)
        history = None if handle is None else handle.message_history
        self.runtime.stash.parked.append(
            ParkedDelegation(
                tool_call_id=delegation.tool_call_id,
                task_id=task_id,
                parent_task_id=delegation.parent_task_id,
                subagent=delegation.name,
                agent_id=delegation.agent_id,
                agent_version_id=delegation.agent_version_id,
                child_run_id=None if handle is None else handle.run_id,
                # The library stores it as text, because it stores what
                # `all_messages_json` produced. Parsed here rather than at the
                # resume so that a history the runner cannot serialise fails while
                # there is still a run to attribute the failure to.
                messages=[] if history is None else list(json.loads(history)),
                spent=self._spent(delegation),
            )
        )

    def resuming(self) -> ResumedDelegation | None:
        """The place this delegation is being continued from, if it is being continued.

        Consulted by the stand-in agent rather than by the toolset, because the
        substitution is a *run* argument - the delegate's own history and the
        verdicts on its parked calls - and the stand-in is where a delegation's run
        arguments are already decided. The toolset would have to reach into the
        library's task machinery to do the same thing.

        Not consumed on read. Keyed by the `task` call, so a second delegation to
        the same delegate later in the run has a different key and starts fresh,
        while the library's own retry of *this* delegation legitimately continues
        from the same point.
        """
        delegation = _CURRENT.get()
        if delegation is None or delegation.tool_call_id is None:
            return None
        return self.runtime.stash.resuming.get(delegation.tool_call_id)

    async def close(self, delegation: Delegation, sink: SubagentEventSink | None) -> None:
        """Settle a delegation whose tool call has returned, or start watching it.

        A sync delegation is finished by the time its call returns, so this is
        where nearly every outcome is recorded. A background one is not: it is kept
        until its task reaches a terminal status, which `settle_background` looks
        for. *When* the settlement happens no longer decides what the delegation is
        recorded as spending - the ledger already knows which requests were its.
        """
        self._running -= 1
        task_id = delegation.task_id
        if task_id is None:
            return
        if not await self.settle(task_id, delegation, sink):
            self._background[task_id] = delegation

    def cancel_in_flight(self) -> None:
        """Finish every delegation still going as cancelled, and report any that ignored it.

        Called from the capability's `wrap_run` before the last settlement, and
        what it exists for is the **sync** delegation of a cancelled turn - the
        default mode, and the one case nothing else covers. `asyncio.CancelledError`
        is a `BaseException`, so the library's `_run_sync` - whose every `except`
        names an `Exception` subclass - never touches the handle when a cancel
        travels through a blocking delegation; and `TaskManager.cancel_all` walks
        `tasks`, which a sync delegation has no entry in, only `handles`. So the
        handle stays `RUNNING`, :func:`_terminal_status` answers `None`,
        :meth:`close` files the delegation into `_background` as "still going" and
        :meth:`settle_background` leaves it there - which is all three failures
        `_terminal_status` exists to prevent, at once: the spend attributed to
        nothing, the fan-out slot never released, and the panel a surface opened
        never closed.

        One sweep on the way out of the run rather than an
        `except asyncio.CancelledError` at each entry point: there are three of
        those, and a `finally` on the run also covers every nesting level, because
        each level wraps its own run with its own journal.

        **A parked delegation is left untouched.** `TaskHandle.finish` records only
        the first terminal transition and `DEFERRED` is already terminal, so a
        delegate waiting on a person keeps that status and stays unrecorded - which
        is the point: the continuation records it when it answers.

        Walked handle-first rather than delegation-first so there is no branch for a
        handle the library has already evicted: there is nothing to finish, and
        :meth:`settle` reads a delegation whose handle is gone as nothing left to
        watch.

        The warning is the honest half of the guarantee. `cancel_all` waits at most
        `cancel_grace_seconds` and then logs and moves on, so a delegate whose
        cleanup swallowed the cancel is *still executing* once the row is written -
        writing into a workspace `finish` closed, and appending to a ledger whose
        `cost_usd` was already persisted. Nothing here can stop it; a line naming
        the delegation is what makes that state diagnosable rather than a cost that
        appears from nowhere.
        """
        for task_id, handle in self.tasks.handles.items():
            if task_id in self._background:
                handle.finish(
                    TaskStatus.CANCELLED, error="The run ended before this delegation finished"
                )
        outlived = [task_id for task_id, task in self.tasks.tasks.items() if not task.done()]
        if outlived:
            logger.warning("delegation_outlived_the_run", extra={"task_ids": outlived})

    async def settle_background(self, sink: SubagentEventSink | None) -> None:
        """Record every background delegation that has finished since the last look.

        Polled rather than pushed, at the two moments the answer is needed: before
        a fan-out check, so a finished task stops occupying a slot, and after the
        run, where the library has already cancelled and awaited whatever was
        still running.

        **The entry is claimed before anything is awaited**, and put back when the
        delegation turns out not to have finished. A plain `del` after the `await`
        was a check-then-act on a dict two coroutines reach: `_delegate` drains
        before its fan-out check and Pydantic AI runs several tool calls from one
        model response concurrently, so two delegations starting together both
        walked the same finished entry the moment the sink yielded. That wrote a
        second child `AgentRun` row for one delegation - double-billing the
        delegate's own monthly total - sent the panel a second `subagent_complete`,
        and raised `KeyError` out of `call_tool` *before* `journal.begin`, where
        nothing settles the delegation and the run dies. Putting the entry back is
        free: :meth:`settle` answers `False` without awaiting anything, so no
        delegation is ever missing from `in_flight` while it is still running.
        """
        for task_id in list(self._background):
            delegation = self._background.pop(task_id, None)
            if delegation is None:
                # A concurrent drain claimed this one and is recording it.
                continue
            if not await self.settle(task_id, delegation, sink):
                self._background[task_id] = delegation

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

        spent = self._spent(delegation)
        run_id = await self._record(
            DelegationOutcome(
                subagent=delegation.name,
                task_id=task_id,
                status=status,
                cost_usd=spent.cost_usd,
                input_tokens=spent.input_tokens,
                output_tokens=spent.output_tokens,
                cost_is_partial=spent.has_unpriced_models,
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
                    cost_usd=spent.cost_usd,
                    input_tokens=spent.input_tokens,
                    output_tokens=spent.output_tokens,
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
        """Make `delegation` the current one, for the library and for the ledger.

        Two context variables, set together because they are two halves of one
        fact - which delegation is running here - and any window in which only one
        of them held would attribute a request to a delegation the panel calls
        something else.

        A context manager so both are reset on the way out however the delegation
        ended: a leaked value would attach the next delegation's task id to this
        record, and book the parent's own later requests to a delegate that has
        already answered.
        """
        token = _CURRENT.set(delegation)
        try:
            with booked_to(delegation.ledger_key):
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

    def _spent(self, delegation: Delegation) -> DelegationSpend:
        """Everything one delegation has cost, this turn and every earlier one.

        The one place the two are added, read by both ends of a park: by
        :meth:`park`, so the next turn starts from a running total rather than from
        what this turn alone booked, and by :meth:`settle`, so the row written when
        the delegation finally ends describes the whole of it.

        `carried` is zero for every delegation that has not parked, which is nearly
        all of them - so this is the ledger share on the ordinary path, and the
        ordinary path is exactly :meth:`_share`.

        `has_unpriced_models` is OR'd rather than replaced, and that is the whole
        reason a park needs the flag at all: a delegate that made an unpriced
        request, parked on an approval and then resumed onto a priced model has a
        share this turn that is exact and a total that is a floor. Taking only this
        turn's answer would let the row claim a precise cost for money nobody
        priced.
        """
        share = self._share(delegation)
        return DelegationSpend(
            cost_usd=delegation.carried.cost_usd + share.cost_usd,
            input_tokens=delegation.carried.input_tokens + share.input_tokens,
            output_tokens=delegation.carried.output_tokens + share.output_tokens,
            has_unpriced_models=delegation.carried.has_unpriced_models or share.has_unpriced_models,
        )

    def _share(self, delegation: Delegation) -> SpendShare:
        """What this delegation booked into the run's ledger, or zeros if nothing meters.

        A `None` ledger is a preview or a test, and zero is the honest answer
        there - reporting a cost nobody measured would be worse than reporting
        none.
        """
        ledger = self.runtime.ledger
        if ledger is None:
            return SpendShare()
        return ledger.share_of(delegation.ledger_key)


def _characteristics(tool_args: dict[str, Any]) -> TaskCharacteristics:
    """The task properties the model reported, as the library's auto mode reads them."""
    return TaskCharacteristics(
        estimated_complexity=tool_args.get("complexity") or "moderate",
        requires_user_context=bool(tool_args.get("requires_user_context")),
        may_need_clarification=bool(tool_args.get("may_need_clarification")),
    )
