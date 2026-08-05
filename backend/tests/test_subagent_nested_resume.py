"""Continuing a run that stopped inside a delegate, and inside a delegate's delegate.

The property everything here exists for is one sentence: **approving a gated tool
inside a delegate has to produce the answer an ungated run of the same work would
have produced.** Nothing else is worth asserting about this, because everything
else was already true while the feature was broken - the parent parked, a row
reached the queue, and a person could decide it. What did not happen is the
decision reaching the call it was made about.

The mechanics of why, since they decide the shape of the whole change. A delegate
whose tool needs a person reaches the run's own approval channel, so the row names
the delegate's tool (`look_up`) and its arguments - the queue is honest. But the
*parent* suspends on its own `task` call, so `DeferredToolRequests.approvals` holds
the delegation, not the delegate's tool. Replaying the parent with the granted
approval therefore presented an id the run never asks about, which Pydantic AI
refuses outright, and the nearest thing to a fix - delegating again - is worse than
the refusal: the delegate starts from nothing, the model need not call the same tool
the second time, and **what a reviewer approved is not what executes**. Nothing
raises.

So a parked run is a tree, each level carries its own conversation and its own
parked calls, and a resume walks it. These tests drive that through the real
capability, the real approval gate and the runner's real splitting of the verdicts -
only the database is stood in for, because which row said yes is the one part of it
that is not interesting.

Two answers legitimately differ between an ungated run and a continued one, and
both are the library's: it appends a chat-trace id to every delegation report, and
those ids are random per delegation. `_answer` strips them, and only them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import RunContext
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolApproved
from pydantic_ai.toolsets import FunctionToolset
from subagents_pydantic_ai import TaskManager

from app.agents.capabilities import CapabilityBinding, build
from app.agents.capabilities.approval import (
    ApprovalGate,
    ApprovalGranted,
    ApprovalRejected,
)
from app.agents.capabilities.budget import SpendEntry, SpendLedger
from app.agents.capabilities.subagents import Delegation
from app.agents.capabilities.subagents._capability import _LazyAgent
from app.agents.capabilities.subagents._journal import DelegationJournal
from app.agents.deps import AgentDeps
from app.agents.subagent_runtime import (
    SUBAGENT_RUNTIME_RESOURCE,
    DelegationOutcome,
    DelegationRecorder,
    DelegationSpend,
    DelegationStash,
    ResolvedSubagent,
    ResumedDelegation,
    SubagentRuntime,
)
from app.db.models.agent_run import ApprovalStatus
from app.services.agent_runner import (
    ApprovalChannel,
    DelegationFrame,
    PausedRunState,
    _delegation_frames,
    _resume_plan,
)

pytestmark = pytest.mark.anyio

SPECIALIST = "researcher"
MIDDLE = "editor"
GATED_TOOL = "look_up"

_TRACE = re.compile(r"\s*Chat Trace ID: [0-9a-f]+", re.MULTILINE)

Charge = Callable[[], None]
"""Spends one request's worth into a run's ledger. See :func:`_charging`."""

INPUT_TOKENS = 7
OUTPUT_TOKENS = 3
"""What one request costs in tokens here - fixed, so a turn's usage is countable."""


@dataclass(frozen=True)
class _Metering:
    """What one turn meters with: the run's single ledger, a charge, and the recorder.

    Bundled because every level of a delegation tree needs all three and they belong
    to the *turn* rather than to a delegate: the ledger is the run's one ledger, the
    recorder writes a row per delegation whatever depth it was at, and the charge is
    what one model request costs in this turn.
    """

    ledger: SpendLedger
    charge: Charge
    record: DelegationRecorder


def _charging(ledger: SpendLedger, cost: Decimal, *, priced: bool = True) -> Charge:
    """A stand-in for the budget guard, charging a known amount per request.

    A fixed entry rather than a real price lookup, for the reason the rest of this
    file stands in for a database: the number under test is what the *journal*
    reports for a delegation, and an unpriced model reports zero however correctly
    it is measured.

    Every agent in a run charges into one ledger, delegates included - that is what
    makes a delegate's spend visible to the parent's cap before its next request,
    and it is why what one delegation cost has to be read back off that shared
    ledger rather than off a ledger of its own.

    Booked rather than appended, which is what the real guard does and is
    load-bearing here: `SpendLedger.book` is the one place an entry is stamped with
    the delegation that made it, so an entry appended around it belongs to the run's
    own agent whoever made it - and every share in this file would be zero.

    `priced=False` is a request `genai-prices` could not price. It costs nothing the
    ledger can see, which is the point: what has to survive the park is the *fact*,
    because the money is not recoverable from the number.
    """

    def charge() -> None:
        ledger.book(
            SpendEntry(
                model_name="test" if priced else "mystery",
                input_tokens=INPUT_TOKENS,
                output_tokens=OUTPUT_TOKENS,
                cost_usd=cost,
                priced=priced,
            )
        )

    return charge


def _answer(result: AgentRunResult[Any]) -> str:
    """A run's answer with the library's per-delegation trace ids taken out.

    They are appended to every delegation report and are random per delegation, so
    they are the one thing two runs of the same work cannot agree on. Stripped
    rather than ignored, so that everything else in the answer stays under
    assertion - including the delegate's report, which is the part that carries
    what a person approved.
    """
    assert isinstance(result.output, str), result.output
    return _TRACE.sub("", result.output)


def _returned(messages: list[ModelMessage]) -> list[str]:
    return [
        str(part.content)
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]


@dataclass
class _Looking(AbstractCapability[AgentDeps]):
    """The one tool the innermost specialist has, contributed as this platform does.

    Through a capability rather than `@agent.tool`, because the approval gate keys
    on `tool_def.capability_id` and deliberately ignores a tool no capability owns.
    A delegate whose tool arrived as a bare agent tool is never gated however it is
    named, so a test built on one would watch the approval be skipped and pass.
    """

    calls: list[dict[str, Any]] = field(default_factory=list)

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        async def look_up(_ctx: RunContext[AgentDeps], city: str) -> str:
            """Look a city's weather up. Side-effecting, for the purposes of the gate."""
            self.calls.append({"city": city})
            return f"{city}: 21C and clear"

        return FunctionToolset([look_up], id="looking")


def _tools_then_report(
    prefix: str, *tools: ToolCallPart, charge: Charge | None = None
) -> FunctionModel:
    """A model that calls each tool in turn, then reports what they all answered.

    Reporting the tools' own words rather than a fixed sentence is what makes "the
    same answer" mean something: an answer that did not depend on the gated call
    would be identical whether or not the approval ever arrived.

    Several tools rather than one because a delegate can need a person more than
    once, and each call is a park of its own - which is the only way to reach a
    delegation whose cost is spread over three turns.

    `charge` spends into the run's ledger, standing in for the budget guard that
    records a real request. One call per request, which is what makes a turn's
    spend a number a test can name.
    """

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if charge is not None:
            charge()
        returned = _returned(messages)
        if len(returned) < len(tools):
            return ModelResponse(parts=[tools[len(returned)]])
        return ModelResponse(parts=[TextPart(f"{prefix}: {' | '.join(returned)}")])

    return FunctionModel(respond)


def _delegating_model(prefix: str, subagent: str, *, charge: Charge | None = None) -> FunctionModel:
    """A model that delegates once and then answers from what came back."""
    return _tools_then_report(
        prefix,
        ToolCallPart("task", {"description": "the weather in Krakow", "subagent_type": subagent}),
        charge=charge,
    )


def _specialist_agent(
    *,
    gated: bool,
    calls: list[dict[str, Any]],
    cities: tuple[str, ...] = ("Krakow",),
    charge: Charge | None = None,
) -> PydanticAgent[Any, Any]:
    looking = _Looking(calls=calls)
    # Stamped the way `app.agents.capabilities.build` stamps it: `capability_id` on
    # the tool definition is what the gate keys on.
    looking.id = "looking"
    return PydanticAgent(
        _tools_then_report(
            "weather",
            *(ToolCallPart(GATED_TOOL, {"city": city}) for city in cities),
            charge=charge,
        ),
        # What `build_agent` gives every agent this platform builds, delegates
        # included. It is why a parked delegate ends its run with an output object
        # instead of raising, which is the route the library reports as suspended.
        output_type=[str, DeferredToolRequests],
        capabilities=(
            [ApprovalGate(required_tool_names=frozenset({GATED_TOOL})), looking]
            if gated
            else [looking]
        ),
    )


def _capability(
    *delegates: ResolvedSubagent,
    stash: DelegationStash,
    depth: int = 0,
    ledger: SpendLedger | None = None,
    record: DelegationRecorder | None = None,
) -> Delegation:
    """The delegation capability as the registry builds it, over a shared stash."""
    runtime = SubagentRuntime(
        subagents=delegates,
        depth_remaining=0,
        depth=depth,
        stash=stash,
        ledger=ledger,
        record=record,
    )
    built = build(
        [CapabilityBinding(capability_id="subagents", config={})],
        resources={SUBAGENT_RUNTIME_RESOURCE: runtime},
    )
    capability = built[0]
    assert isinstance(capability, Delegation)
    return capability


def _resolved(
    name: str, build_it: Callable[[], PydanticAgent[Any, Any]], *, agent_id: UUID | None = None
) -> ResolvedSubagent:
    return ResolvedSubagent(
        name=name, description=f"The {name}.", build=build_it, agent_id=agent_id
    )


def _specialist_delegate(
    *,
    gated: bool,
    calls: list[dict[str, Any]],
    agent_id: UUID | None = None,
    cities: tuple[str, ...] = ("Krakow",),
    charge: Charge | None = None,
) -> ResolvedSubagent:
    return _resolved(
        SPECIALIST,
        lambda: _specialist_agent(gated=gated, calls=calls, cities=cities, charge=charge),
        agent_id=agent_id,
    )


def _middle_delegate(
    *,
    gated: bool,
    calls: list[dict[str, Any]],
    stash: DelegationStash,
    metering: _Metering | None = None,
) -> ResolvedSubagent:
    """A delegate that delegates on, so the gated tool sits two levels down.

    Built the way the runner builds one: its own delegation capability, its own
    runtime, and the *same* stash - which is what lets the run somebody started be
    continued from a place two levels below it.

    The metering goes to the *specialist* and to the middle's own capability, and
    deliberately not to the middle's model: the specialist is the level whose spend
    is being followed across a park, and a middle that charged as well would put its
    own requests inside its subtree's total, which is a different defect
    (agenticos#180) and not this one.
    """

    def build_it() -> PydanticAgent[Any, Any]:
        return PydanticAgent(
            _delegating_model("edited", SPECIALIST),
            output_type=[str, DeferredToolRequests],
            capabilities=[
                _capability(
                    _specialist_delegate(
                        gated=gated,
                        calls=calls,
                        charge=None if metering is None else metering.charge,
                    ),
                    stash=stash,
                    depth=1,
                    ledger=None if metering is None else metering.ledger,
                    record=None if metering is None else metering.record,
                )
            ],
        )

    return _resolved(MIDDLE, build_it)


def _orchestrator(
    delegate: ResolvedSubagent,
    *,
    stash: DelegationStash,
    channel: ApprovalChannel,
    ledger: SpendLedger | None = None,
    record: DelegationRecorder | None = None,
    charge: Charge | None = None,
) -> tuple[PydanticAgent[Any, Any], AgentDeps]:
    """The run somebody started: it delegates once and answers from the report."""
    agent = PydanticAgent(
        _delegating_model("answer", delegate.name, charge=charge),
        output_type=[str, DeferredToolRequests],
        capabilities=[_capability(delegate, stash=stash, ledger=ledger, record=record)],
    )
    deps = AgentDeps(organization_id=uuid4(), run_id=uuid4(), request_approval=channel)
    return agent, deps


@dataclass
class _Row:
    """A `tool_approvals` row, carrying only what a resume reads off one."""

    id: UUID
    tool_id: str
    tool_args: dict[str, Any]
    subagent_name: str | None
    subagent_agent_id: UUID | None
    status: str = ApprovalStatus.PENDING.value
    note: str | None = None


class _Queue:
    """`ApprovalService`, without a database.

    Stood in for rather than mocked out, because the real `ApprovalChannel` is under
    test: it is what decides which delegate a row is attributed to, and it is where
    a parked call is tied to the agent whose replay it belongs to.
    """

    def __init__(self) -> None:
        self.rows: list[_Row] = []

    async def request(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        agent_id: UUID,
        tool_id: str,
        tool_args: dict[str, Any],
        subagent_name: str | None = None,
        subagent_agent_id: UUID | None = None,
    ) -> _Row:
        row = _Row(
            id=uuid4(),
            tool_id=tool_id,
            tool_args=tool_args,
            subagent_name=subagent_name,
            subagent_agent_id=subagent_agent_id,
        )
        self.rows.append(row)
        return row

    def decide(self, *, approved: bool, note: str | None = None) -> None:
        for row in self.rows:
            row.status = (
                ApprovalStatus.APPROVED.value if approved else ApprovalStatus.REJECTED.value
            )
            row.note = note


def _channel(queue: _Queue, decided: dict[str, Any] | None = None) -> ApprovalChannel:
    return ApprovalChannel(
        approvals=queue,  # ty: ignore[invalid-argument-type] - the queue above stands in
        organization_id=uuid4(),
        agent_id=uuid4(),
        run_id=uuid4(),
        decided=decided or {},
    )


@dataclass
class _Parked:
    """A run that stopped, as the row would hold it, plus the queue it filled."""

    state: PausedRunState
    queue: _Queue
    channel: ApprovalChannel
    result: AgentRunResult[Any]


async def _park(delegate: ResolvedSubagent, stash: DelegationStash) -> _Parked:
    """Run the orchestrator until it parks, and record the state a row would keep.

    Assembled exactly as `AgentRunnerService` assembles it - `_run` supplies the
    messages and the channel's parked calls, `finish` folds in the delegation tree
    and which delegate each approval came from - so what these tests continue from is
    what a real run would have written.
    """
    queue = _Queue()
    channel = _channel(queue)
    agent, deps = _orchestrator(delegate, stash=stash, channel=channel)
    result = await agent.run("what is the weather in Krakow", deps=deps)
    assert isinstance(result.output, DeferredToolRequests), result.output
    return _Parked(
        state=_parked_state(result, channel=channel, stash=stash),
        queue=queue,
        channel=channel,
        result=result,
    )


def _parked_state(
    result: AgentRunResult[Any], *, channel: ApprovalChannel, stash: DelegationStash
) -> PausedRunState:
    """The row a parked turn leaves, assembled the way `_run` and `finish` assemble it.

    The surface supplies the messages and its channel's parked calls; the runner
    folds in the delegation tree and which delegate each approval came from. Shared
    by every turn of a run that parks more than once, because the second park is
    written by exactly the same code as the first.
    """
    return PausedRunState(
        messages=ModelMessagesTypeAdapter.dump_python(result.all_messages(), mode="json"),
        tool_call_ids=channel.parked,
        delegated_approvals={
            str(parked.approval_id): parked.task_id
            for parked in channel.requested
            if parked.task_id is not None
        },
        delegations=_delegation_frames(stash.parked),
    )


def _verdicts(
    state: PausedRunState, queue: _Queue
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The decisions on a parked run's calls, the way `_decisions` derives them."""
    by_call = {str(row.id): row for row in queue.rows}
    decided: dict[str, Any] = {}
    approved_args: dict[str, dict[str, Any]] = {}
    for approval_id, tool_call_id in state.tool_call_ids.items():
        row = by_call[approval_id]
        decided[tool_call_id] = (
            ApprovalGranted(tool_args=row.tool_args)
            if row.status == ApprovalStatus.APPROVED.value
            else ApprovalRejected(note=row.note)
        )
        approved_args[tool_call_id] = row.tool_args
    return decided, approved_args


async def _resume(parked: _Parked, delegate: Callable[[DelegationStash], ResolvedSubagent]) -> Any:
    """Continue a parked run the way `resume` does: fresh everything, loaded stash.

    Nothing is reused from the first turn. The runner reassembles the whole tree
    from the parked run's version, which is why the delegate is built again from a
    factory here rather than handed over - a stash that only worked against the
    objects that filled it would work in a test and nowhere else.
    """
    decided, approved_args = _verdicts(parked.state, parked.queue)
    plan = _resume_plan(parked.state, approved_args)
    stash = DelegationStash(resuming=plan.delegations, spent=plan.spent)
    agent, deps = _orchestrator(
        delegate(stash), stash=stash, channel=_channel(parked.queue, decided=decided)
    )
    return await agent.run(
        None,
        deps=deps,
        message_history=ModelMessagesTypeAdapter.validate_python(parked.state.messages),
        deferred_tool_results=plan.results,
    )


class TestOneLevelDown:
    """A gated tool inside a delegate: the shape #40 promised would be supported."""

    async def test_approving_it_answers_what_an_ungated_run_would_have(self):
        """The test this whole change exists to pass.

        Everything else here - the tree on the run row, the frame, the stash - is
        plumbing in service of this one sentence, and plumbing that passes its own
        tests while this fails is the failure mode worth naming: before the change
        the parked run could not be continued at all, and the obvious repair -
        delegating again - answers from a second conversation the reviewer never saw.
        """
        ungated_calls: list[dict[str, Any]] = []
        ungated_agent, ungated_deps = _orchestrator(
            _specialist_delegate(gated=False, calls=ungated_calls),
            stash=DelegationStash(),
            channel=_channel(_Queue()),
        )
        expected = _answer(
            await ungated_agent.run("what is the weather in Krakow", deps=ungated_deps)
        )

        gated_calls: list[dict[str, Any]] = []
        stash = DelegationStash()
        parked = await _park(_specialist_delegate(gated=True, calls=gated_calls), stash)
        assert gated_calls == [], "the gate must park before the tool body runs"
        parked.queue.decide(approved=True)

        resumed = await _resume(
            parked, lambda _stash: _specialist_delegate(gated=True, calls=gated_calls)
        )

        assert _answer(resumed) == expected
        assert "21C and clear" in expected, "the answer has to depend on the gated call"
        # Once, on the arguments the row was written with. A second call would mean
        # the delegation had been re-run rather than continued.
        assert gated_calls == [{"city": "Krakow"}]

    async def test_the_queue_names_the_delegate_and_the_tool_it_is_calling(self):
        """`task` is what parked the run; `look_up` is what somebody has to decide.

        The row was already right about the tool - the delegate's own gate writes it
        - and said nothing about who was calling it. A queue of tool names with no
        actor is a queue people approve blind, and `agent_id` on the row cannot
        answer it: that is the agent whose *run* this is, which is how the queue is
        scoped in the first place.
        """
        delegate_agent_id = uuid4()
        parked = await _park(
            _specialist_delegate(gated=True, calls=[], agent_id=delegate_agent_id),
            DelegationStash(),
        )

        (row,) = parked.queue.rows
        assert row.tool_id == GATED_TOOL
        assert row.subagent_name == SPECIALIST
        assert row.subagent_agent_id == delegate_agent_id

    async def test_an_inline_specialist_is_named_without_an_agent_id(self):
        """It has none, and inventing one would create a second kind of agent.

        A specialist is defined inside its parent's spec, is not versioned, and
        nothing outside that spec can reference it - so the permission model cannot
        see it. The name is what a reviewer reads either way.
        """
        parked = await _park(_specialist_delegate(gated=True, calls=[]), DelegationStash())

        (row,) = parked.queue.rows
        assert (row.subagent_name, row.subagent_agent_id) == (SPECIALIST, None)

    async def test_the_parked_run_records_which_delegate_it_stopped_inside(self):
        """What makes the tree walkable, and what a surface needs to explain the wait."""
        stash = DelegationStash()
        parked = await _park(_specialist_delegate(gated=True, calls=[]), stash)

        (frame,) = parked.state.delegations
        assert frame.subagent == SPECIALIST
        assert frame.parent_task_id is None
        assert frame.child_run_id is not None
        assert frame.messages, "without the delegate's conversation there is nothing to continue"
        # The `task` call the parent parked on, which is what the replay presents.
        assert [call.tool_name for call in parked.result.output.approvals] == ["task"]
        assert frame.tool_call_id == parked.result.output.approvals[0].tool_call_id

    async def test_a_delegate_that_suspended_never_reaches_the_parent_as_text(self):
        """A suspension is not a report, and it used to be serialised as one.

        `DeferredToolRequests` is a dataclass, so the parent's model was handed
        `{"calls": [], "approvals": [...]}` as the specialist's answer with the task
        marked completed - on this platform's default path, since every agent
        `build_agent` makes declares that output type. Fixed upstream, pinned here
        because the failure is an agent confidently summarising a dataclass.
        """
        parked = await _park(_specialist_delegate(gated=True, calls=[]), DelegationStash())

        reports = _returned(parked.result.all_messages())
        assert reports == [], f"a parked delegation produced a tool result: {reports!r}"
        assert "approvals" not in str(parked.state.messages)

    async def test_a_rejected_call_is_refused_by_the_gate_rather_than_run(self):
        """The delegation is continued either way: a refusal is an answer.

        `_resume_plan` approves every parked call, and that only means "let it reach
        the tool pipeline" - the gate is the single place allowed to decide whether a
        gated tool runs, and it reads the recorded verdict. Two sources of truth for
        a refusal is how one of them ends up stale.
        """
        calls: list[dict[str, Any]] = []
        parked = await _park(_specialist_delegate(gated=True, calls=calls), DelegationStash())
        parked.queue.decide(approved=False, note="not this city")

        resumed = await _resume(
            parked, lambda _stash: _specialist_delegate(gated=True, calls=calls)
        )

        assert calls == [], "a rejected call must not reach the tool body"
        assert "not this city" in _answer(resumed)
        assert "21C" not in _answer(resumed)


class TestEitherEntryPoint:
    """The library drives a delegation through `iter` or `run`, and picks per delegate.

    `iter` when retries are on, which is its default and therefore every delegation
    this platform makes today; `run` when a config turns them off. A substitution on
    only the path in use is one that disappears the day that config changes - and it
    would disappear silently, into "the delegation started again and answered
    something else".
    """

    @pytest.mark.parametrize("entry", ["run", "iter"])
    async def test_continues_the_delegate_rather_than_starting_it(self, entry: str):
        calls: list[dict[str, Any]] = []
        delegate = _specialist_delegate(gated=True, calls=calls)
        resumed, decided = await _park_the_specialist_alone(gated=True)
        journal = _journal_mid_delegation(delegate, resuming={"the-task-call": resumed})
        proxy = _LazyAgent(delegate, journal)
        deps = AgentDeps(request_approval=_channel(_Queue(), decided=decided))

        with journal.delegating(
            journal.begin(
                delegate=delegate,
                name=SPECIALIST,
                prompt="the weather in Krakow",
                tool_args={},
                tool_call_id="the-task-call",
            )
        ):
            answer = await _drive(proxy, entry, deps)

        assert answer == "weather: Krakow: 21C and clear"
        assert calls == [{"city": "Krakow"}]


async def _drive(proxy: _LazyAgent, entry: str, deps: AgentDeps) -> Any:
    """Run the stand-in through one of the two entry points the library uses."""
    if entry == "run":
        return (await proxy.run("## Your Task\n\nthe weather in Krakow", deps=deps)).output
    async with proxy.iter("## Your Task\n\nthe weather in Krakow", deps=deps) as run:
        async for _ in run:
            pass
    return run.result.output


async def _park_the_specialist_alone(*, gated: bool) -> tuple[Any, dict[str, Any]]:
    """A suspended specialist's place, and the verdicts it is waiting on.

    Parked on its own rather than through a delegation, because what is under test
    below is the stand-in's substitution and nothing else. The place is real: a real
    gate asked, a real run ended with its parked calls as its output.
    """
    queue = _Queue()
    channel = _channel(queue)
    result = await _specialist_agent(gated=gated, calls=[]).run(
        "the weather in Krakow", deps=AgentDeps(request_approval=channel)
    )
    assert isinstance(result.output, DeferredToolRequests)
    queue.decide(approved=True)
    return (
        ResumedDelegation(
            messages=result.all_messages(),
            results=DeferredToolResults(
                approvals={call.tool_call_id: ToolApproved() for call in result.output.approvals}
            ),
        ),
        {
            parked.tool_call_id: ApprovalGranted(tool_args=parked.tool_args)
            for parked in channel.requested
        },
    )


def _journal_mid_delegation(
    delegate: ResolvedSubagent, *, resuming: dict[str, Any]
) -> DelegationJournal:
    """A journal whose stash already holds a place to continue from."""
    journal = DelegationJournal(
        runtime=SubagentRuntime(subagents=(delegate,), stash=DelegationStash(resuming=resuming)),
        mode="sync",
        max_fanout=3,
        depth=0,
    )
    journal.tasks = TaskManager()
    return journal


class TestWhenAPlaceCannotBeKept:
    """A frame with no conversation: re-run the delegation, never strand the run."""

    def test_the_delegating_call_is_answered_even_with_nothing_to_continue(self):
        """Otherwise the run could not be continued at all, which is the worse failure.

        The library stores a delegate's history as best-effort telemetry, so a frame
        can arrive with none. Pydantic AI refuses a resume that leaves a parked call
        without a result, and the parked call is the parent's `task` - so leaving the
        frame out would turn a delegation that has to start again into a run nobody
        can ever finish.
        """
        state = PausedRunState(
            messages=[],
            tool_call_ids={},
            delegations=[
                DelegationFrame(
                    tool_call_id="the-task-call",
                    task_id="4f2a1b8c",
                    subagent=SPECIALIST,
                    cost_usd=Decimal("0.25"),
                    input_tokens=INPUT_TOKENS,
                    output_tokens=OUTPUT_TOKENS,
                )
            ],
        )

        plan = _resume_plan(state, {})

        assert list(plan.results.approvals) == ["the-task-call"]
        assert plan.delegations == {}, "nothing to continue, so nothing is offered"
        # But what it cost is still carried, which is the half that does not depend
        # on the library having kept the conversation. The delegation runs again
        # from the start and the row written when it ends covers both attempts,
        # because the organization paid for both.
        assert plan.spent == {
            "the-task-call": DelegationSpend(
                cost_usd=Decimal("0.25"),
                input_tokens=INPUT_TOKENS,
                output_tokens=OUTPUT_TOKENS,
            )
        }


class TestAnOlderParkedRun:
    """A run parked before any of this existed has to stay resumable.

    `PausedRunState` forbids extra keys and is read back out of a JSONB column, so
    the compatibility that matters runs the other way: every field delegation added
    has to have a default that reads as "this run delegated nothing". A run parked
    the day before a deploy is otherwise a run nobody can ever finish, and the person
    who approved its tool call is never told why.
    """

    async def test_the_two_keys_the_state_used_to_hold_still_resume(self):
        """The payload is produced, not written: a real agent, a real gate, a real park.

        Only the two fields the pre-change model declared - `messages` and
        `tool_call_ids` - are kept, which is exactly what
        `PausedRunState.model_dump(mode="json")` wrote before this change. A
        hand-shaped dict would prove that some dict validates; this proves that the
        one already sitting in the column does.
        """
        calls: list[dict[str, Any]] = []
        queue = _Queue()
        channel = _channel(queue)
        agent = _specialist_agent(gated=True, calls=calls)
        parked = await agent.run("the weather in Krakow", deps=AgentDeps(request_approval=channel))
        assert isinstance(parked.output, DeferredToolRequests)
        stored: dict[str, Any] = {
            "messages": ModelMessagesTypeAdapter.dump_python(parked.all_messages(), mode="json"),
            "tool_call_ids": dict(channel.parked),
        }
        queue.decide(approved=True)

        state = PausedRunState.model_validate(stored)
        assert (state.delegations, state.delegated_approvals) == ([], {})
        plan = _resume_plan(
            state, {parked.tool_call_id: parked.tool_args for parked in channel.requested}
        )
        resumed = await agent.run(
            None,
            deps=AgentDeps(
                request_approval=_channel(
                    queue,
                    decided={
                        entry.tool_call_id: ApprovalGranted(tool_args=entry.tool_args)
                        for entry in channel.requested
                    },
                )
            ),
            message_history=ModelMessagesTypeAdapter.validate_python(state.messages),
            deferred_tool_results=plan.results,
        )

        assert _answer(resumed) == "weather: Krakow: 21C and clear"
        assert calls == [{"city": "Krakow"}]


class TestTwoLevelsDown:
    """A gated tool inside a delegate's own specialist.

    Worth its own class because the middle level parks for a reason of its own: its
    `task` call suspends exactly as the run's did, so the tree is genuinely
    recursive and a resume that only walked one level would re-run the middle
    delegation and lose the specialist's place inside it.
    """

    async def test_approving_it_answers_what_an_ungated_run_would_have(self):
        ungated_calls: list[dict[str, Any]] = []
        ungated_stash = DelegationStash()
        ungated_agent, ungated_deps = _orchestrator(
            _middle_delegate(gated=False, calls=ungated_calls, stash=ungated_stash),
            stash=ungated_stash,
            channel=_channel(_Queue()),
        )
        expected = _answer(
            await ungated_agent.run("what is the weather in Krakow", deps=ungated_deps)
        )

        calls: list[dict[str, Any]] = []
        stash = DelegationStash()
        parked = await _park(_middle_delegate(gated=True, calls=calls, stash=stash), stash)
        parked.queue.decide(approved=True)

        resumed = await _resume(
            parked, lambda new: _middle_delegate(gated=True, calls=calls, stash=new)
        )

        assert _answer(resumed) == expected
        assert "edited" in expected and "weather" in expected, "both levels have to answer"
        assert calls == [{"city": "Krakow"}]

    async def test_the_tree_nests_rather_than_flattening(self):
        """Each level's conversation belongs to that level, and only to it.

        Flattening is not a cosmetic loss. Pydantic AI refuses a resume whose results
        name a call the replayed response does not contain, so handing one level's
        parked call to another's replay fails the whole continuation - which is what a
        single flat mapping of approvals did.
        """
        stash = DelegationStash()
        parked = await _park(_middle_delegate(gated=True, calls=[], stash=stash), stash)

        # Through the column and back, because that is the trip it actually makes:
        # `paused_state` is JSONB and the resume validates whatever is in it.
        stored = PausedRunState.model_validate(parked.state.model_dump(mode="json"))

        (outer,) = stored.delegations
        assert outer.subagent == MIDDLE
        (inner,) = outer.delegations
        assert inner.subagent == SPECIALIST
        assert inner.parent_task_id == outer.task_id
        assert inner.delegations == []
        # The approval was raised by the innermost delegate, and is recorded against
        # that delegation rather than against the one the run's own agent made.
        (row,) = parked.queue.rows
        assert row.subagent_name == SPECIALIST
        assert parked.state.delegated_approvals == {str(row.id): inner.task_id}


class Recorder:
    """Stands in for the runner, which writes a child `AgentRun` row per delegation.

    One recorder for a whole sequence of turns, because that is the question a park
    raises: a delegation that stopped twice must leave **one** row, holding
    everything it spent. A row per turn would divide one delegate's work into two
    agents' worth of history and bill neither of them correctly.
    """

    def __init__(self) -> None:
        self.outcomes: list[DelegationOutcome] = []

    async def __call__(self, outcome: DelegationOutcome) -> UUID | None:
        self.outcomes.append(outcome)
        return None


async def _until_it_answers(
    delegate: Callable[[DelegationStash, _Metering], ResolvedSubagent],
    *,
    turn_costs: tuple[Decimal, ...],
    parent_cost: Decimal,
    recorder: Recorder,
    unpriced_turns: frozenset[int] = frozenset(),
) -> tuple[list[PausedRunState], str]:
    """Drive the orchestrator through however many parks it takes, and answer.

    One delegate cost per turn, and they differ deliberately: a sum is only provable
    when no single segment can pass for the total, and neither can the ledger any one
    turn ends with - the parent charges into it too.

    `unpriced_turns` names the turns, by index, whose delegate ran on a model nothing
    could price. Only the delegate's: an unpriced *parent* is the case that used to
    mark every child row in the run a floor, and it is a different assertion.

    Every turn is rebuilt from nothing but the stored state, exactly as `resume`
    rebuilds one: a fresh ledger, a fresh stash, a fresh capability, a fresh agent.
    That is the whole of the defect being pinned - a turn cannot see the ledger the
    previous turn measured against, so anything it needs from that turn has to have
    been written down.

    Returns the state each park left, in order, and the answer the last turn gave.
    """
    queue = _Queue()
    parked: list[PausedRunState] = []
    state: PausedRunState | None = None
    for turn, cost in enumerate(turn_costs):
        ledger = SpendLedger()
        decided: dict[str, Any] = {}
        stash = DelegationStash()
        history: list[ModelMessage] | None = None
        results: DeferredToolResults | None = None
        if state is not None:
            decided, approved_args = _verdicts(state, queue)
            plan = _resume_plan(state, approved_args)
            stash = DelegationStash(resuming=plan.delegations, spent=plan.spent)
            history = ModelMessagesTypeAdapter.validate_python(state.messages)
            results = plan.results
        channel = _channel(queue, decided=decided)
        metering = _Metering(
            ledger=ledger,
            charge=_charging(ledger, cost, priced=turn not in unpriced_turns),
            record=recorder,
        )
        agent, deps = _orchestrator(
            delegate(stash, metering),
            stash=stash,
            channel=channel,
            ledger=ledger,
            record=recorder,
            charge=_charging(ledger, parent_cost),
        )
        result = await agent.run(
            "what is the weather in Krakow" if state is None else None,
            deps=deps,
            message_history=history,
            deferred_tool_results=results,
        )
        if not isinstance(result.output, DeferredToolRequests):
            return parked, _answer(result)
        queue.decide(approved=True)
        # Through the column and back, because that is the trip a park actually
        # makes: `paused_state` is JSONB, so a cost is stored as the string
        # `model_dump(mode="json")` writes and the next turn resumes from whatever
        # validates out of it.
        state = PausedRunState.model_validate(
            _parked_state(result, channel=channel, stash=stash).model_dump(mode="json")
        )
        parked.append(state)
    pytest.fail(f"still parked after {len(turn_costs)} turns: {parked[-1].tool_call_ids}")


class TestWhatADelegateSpentBeforeItParked:
    """A delegation's cost is every turn it ran in, not the last one.

    The shape of the failure this class exists for: a delegate does the work, then
    asks permission to act on the result. So by the time it parks it has spent nearly
    everything it is going to spend - and each turn measures against a ledger of its
    own, which the next turn never sees. The delegation was recorded at what it spent
    *after* the last resume.

    Nothing failed to add up, which is why it survived: the money was in the parent's
    row all along. What was wrong is every number that answers "what did this
    delegate cost" - its `AgentRun` row, the `monthly_spend` that sums those rows, and
    the budget alert that fires on the total.
    """

    async def test_a_delegation_that_parked_is_recorded_with_both_halves(self):
        """One park: the work before the approval, and the work after it.

        The two turns spend different amounts so that neither can be mistaken for the
        sum, and the parent spends as well so that neither can the ledger.
        """
        calls: list[dict[str, Any]] = []
        recorder = Recorder()

        parked, answer = await _until_it_answers(
            lambda _stash, metering: _specialist_delegate(
                gated=True, calls=calls, charge=metering.charge, agent_id=uuid4()
            ),
            turn_costs=(Decimal("0.25"), Decimal("0.75")),
            parent_cost=Decimal("0.10"),
            recorder=recorder,
        )

        assert answer == "answer: weather: Krakow: 21C and clear"
        assert calls == [{"city": "Krakow"}], "continued, so the gated call ran once"
        assert len(parked) == 1
        (outcome,) = recorder.outcomes
        assert outcome.status == "completed"
        assert outcome.cost_usd == Decimal("1.00")
        assert (outcome.input_tokens, outcome.output_tokens) == (
            INPUT_TOKENS * 2,
            OUTPUT_TOKENS * 2,
        )
        # Both segments were priced, so the sum is a cost rather than a floor. The
        # other direction is the test below it.
        assert outcome.cost_is_partial is False

    async def test_an_unpriced_segment_before_the_approval_still_marks_the_row(self):
        """A park must not turn a floor into a precise number.

        `cost_is_partial` is read per delegation now rather than off the whole run, so
        it is a fact only the segment that saw it knows. A delegate that made an
        unpriced request, parked, and resumed onto a priced model has a share this
        turn that is exact - and taking only that answer would have the row claim
        $0.75 for a delegation whose real cost nobody can name.
        """
        recorder = Recorder()

        _parked, answer = await _until_it_answers(
            lambda _stash, metering: _specialist_delegate(
                gated=True, calls=[], charge=metering.charge, agent_id=uuid4()
            ),
            turn_costs=(Decimal("0.25"), Decimal("0.75")),
            parent_cost=Decimal("0.10"),
            recorder=recorder,
            unpriced_turns=frozenset({0}),
        )

        assert answer == "answer: weather: Krakow: 21C and clear"
        (outcome,) = recorder.outcomes
        assert outcome.cost_is_partial is True
        # And the money the turn *could* price is still reported, because a floor is
        # only useful if it is the highest one known.
        assert outcome.cost_usd == Decimal("1.00")

    async def test_two_parks_count_all_three_segments_once_each(self):
        """A delegate can need a person twice, and the totals have to keep adding up.

        The park has to carry a *running* total rather than the turn that wrote it:
        carrying only the last turn's delta would record the second and third
        segments and drop the first, which is the same bug one level along and would
        pass the test above.

        Three distinct costs, so every wrong combination is a different number:
        $0.75 is the last two, $1.25 the first and last, $1.00 the first two, and
        only $1.50 is all three.
        """
        calls: list[dict[str, Any]] = []
        recorder = Recorder()

        parked, answer = await _until_it_answers(
            lambda _stash, metering: _specialist_delegate(
                gated=True, calls=calls, cities=("Krakow", "Warsaw"), charge=metering.charge
            ),
            turn_costs=(Decimal("0.25"), Decimal("0.75"), Decimal("0.50")),
            parent_cost=Decimal("0.10"),
            recorder=recorder,
        )

        assert answer == ("answer: weather: Krakow: 21C and clear | Warsaw: 21C and clear"), (
            "both approved calls have to reach the answer"
        )
        assert calls == [{"city": "Krakow"}, {"city": "Warsaw"}]
        (outcome,) = recorder.outcomes
        assert outcome.cost_usd == Decimal("1.50")
        assert (outcome.input_tokens, outcome.output_tokens) == (
            INPUT_TOKENS * 3,
            OUTPUT_TOKENS * 3,
        )
        # And the intermediate park carries the running sum rather than its own turn,
        # which is what makes the third turn's arithmetic possible at all.
        assert [frame.cost_usd for state in parked for frame in state.delegations] == [
            Decimal("0.25"),
            Decimal("1.00"),
        ]

    async def test_a_specialist_two_levels_down_keeps_its_own_spend(self):
        """The parked state is a tree, so what each level spent belongs to that level.

        The middle delegate parks for a reason of its own - its `task` call suspends
        exactly as the run's did - so a carry stored per run rather than per delegation
        would attribute the specialist's work to the editor, or to nothing.
        """
        calls: list[dict[str, Any]] = []
        recorder = Recorder()

        parked, answer = await _until_it_answers(
            lambda stash, metering: _middle_delegate(
                gated=True, calls=calls, stash=stash, metering=metering
            ),
            turn_costs=(Decimal("0.25"), Decimal("0.75")),
            parent_cost=Decimal("0.10"),
            recorder=recorder,
        )

        assert answer == "answer: edited: weather: Krakow: 21C and clear"
        assert calls == [{"city": "Krakow"}]
        # The specialist's own row holds what the specialist spent across both turns.
        # The editor's holds its subtree, which is the separate defect agenticos#180
        # is about and is deliberately not asserted here.
        specialist = [outcome for outcome in recorder.outcomes if outcome.subagent == SPECIALIST]
        assert [outcome.cost_usd for outcome in specialist] == [Decimal("1.00")]
        # Nested where it was made, which is what keeps one level's carry off another.
        (outer,) = parked[0].delegations
        (inner,) = outer.delegations
        assert (outer.subagent, inner.subagent) == (MIDDLE, SPECIALIST)
        assert inner.cost_usd == Decimal("0.25")
