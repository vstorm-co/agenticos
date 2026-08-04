"""The delegation capability - what it offers, what it refuses, what it records.

Delegation is the one capability whose failures are all quiet. A delegate that
runs but is never recorded spends real money against nothing; a fan-out ceiling
that does not bind lets one turn start a dozen agents; a mode nobody enforces
turns a blocking delegation into a background one whose answer arrives after the
run has ended. None of those look like errors, so each one is pinned here.

Every model is `TestModel` or `FunctionModel`: a delegation is a whole second
agent run, and this suite would otherwise be the most expensive one in the
repository.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import anyio
import pytest
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai._run_context import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ApprovalRequired, UsageLimitExceeded
from pydantic_ai.messages import (
    AgentStreamEvent,
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage, UsageLimits
from subagents_pydantic_ai import SubAgentConfig

from app.agents.capabilities import CapabilityBinding, CapabilityBuildContext, build, get
from app.agents.capabilities.approval import (
    ApprovalGate,
    ApprovalPending,
    ApprovalRequest,
    approval_required_tools,
)
from app.agents.capabilities.budget import SpendEntry, SpendLedger
from app.agents.capabilities.subagents import Delegation, SubagentsConfig
from app.agents.capabilities.subagents._capability import _LazyAgent
from app.agents.capabilities.subagents._events import UNNAMED_TOOL, FrameLabels, frame_for
from app.agents.deps import AgentDeps
from app.agents.factory import DEFAULT_MAX_STEPS
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.agents.subagent_events import SubagentEvent
from app.agents.subagent_runtime import (
    SUBAGENT_RUNTIME_RESOURCE,
    DelegationOutcome,
    ResolvedSubagent,
    SubagentRuntime,
)

pytestmark = pytest.mark.anyio

ENTRY = SpendEntry(
    model_name="test", input_tokens=7, output_tokens=3, cost_usd=Decimal("0.25"), priced=True
)
"""What one delegate request costs in these tests.

A fixed entry appended by the delegate's own model rather than a real price
lookup: the number under test is the *delta* the journal measures, and a delta of
an unpriced model is zero however correct the measurement is.
"""


def answering(text: str = "found it", *, ledger: SpendLedger | None = None) -> FunctionModel:
    """A model that answers once, spending into the run's ledger if there is one.

    Standing in for the budget guard, which is what records a real request. The
    delegate spends into the *parent's* ledger by construction - that is the whole
    reason a delegation's cost can be measured as a delta at all.

    Both halves are supplied because a delegation on a surface that narrates it is
    *streamed*: the library resolves an event handler, which puts the delegate's
    run on `iter` rather than `run`, and a `FunctionModel` with no
    `stream_function` raises there.
    """

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if ledger is not None:
            ledger.entries.append(ENTRY)
        return ModelResponse(parts=[TextPart(text)])

    async def stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        if ledger is not None:
            ledger.entries.append(ENTRY)
        yield text

    return FunctionModel(respond, stream_function=stream)


def looping() -> FunctionModel:
    """A model that calls the same tool forever, so only a step limit stops it."""

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("ping", {})])

    async def stream(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[DeltaToolCalls]:
        yield {0: DeltaToolCall(name="ping", json_args="{}")}

    return FunctionModel(respond, stream_function=stream)


def blocking() -> FunctionModel:
    """A model that never answers within a test, so a delegation stays in flight."""

    async def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        await anyio.sleep(30)
        return ModelResponse(parts=[TextPart("too late")])

    async def stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        await anyio.sleep(30)
        yield "too late"

    return FunctionModel(respond, stream_function=stream)


def _tool_results(messages: list[ModelMessage]) -> list[str]:
    return [
        str(part.content)
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]


def one_tool_call(text: str | None = "found it") -> FunctionModel:
    """A model that calls its tool once and then answers from the result.

    `text=None` makes it answer *with* the result rather than in spite of it,
    which is the only way a tool's own words - a refusal, say - reach anything a
    test can read: `wait_tasks` and `check_task` carry the delegate's answer, not
    its transcript.
    """

    def answer(messages: list[ModelMessage]) -> str:
        return " ".join(_tool_results(messages)) if text is None else text

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if _tool_results(messages):
            return ModelResponse(parts=[TextPart(answer(messages))])
        return ModelResponse(parts=[ToolCallPart("ping", {})])

    async def stream(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        if _tool_results(messages):
            yield answer(messages)
        else:
            yield {0: DeltaToolCall(name="ping", json_args="{}")}

    return FunctionModel(respond, stream_function=stream)


def steerable() -> FunctionModel:
    """A model that calls its tool, then answers with every instruction it was given.

    Two requests, which is what makes steering observable: the library drains the
    parent's messages at a node boundary, so a message that arrived while the
    tool was running is injected before the second request and appears in the
    answer - and one that never arrived is visibly absent from it.
    """

    def instructions(messages: list[ModelMessage]) -> str:
        return " | ".join(
            str(part.content)
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if _tool_results(messages):
            return ModelResponse(parts=[TextPart(instructions(messages))])
        return ModelResponse(parts=[ToolCallPart("ping", {})])

    async def stream(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        if _tool_results(messages):
            yield instructions(messages)
        else:
            yield {0: DeltaToolCall(name="ping", json_args="{}")}

    return FunctionModel(respond, stream_function=stream)


@dataclass
class Pinging(AbstractCapability[AgentDeps]):
    """The one tool a delegate here has, contributed the way this platform contributes every tool.

    Through a capability rather than `@agent.tool`, and not for tidiness: the
    approval gate deliberately ignores a tool no capability owns - an MCP
    server's, say - and `tool_def.capability_id` is how it tells the difference. A
    delegate whose tool arrived as a bare agent tool is therefore never gated,
    however it is named, so a test built on one would watch a delegate's approval
    be skipped and call that a pass.
    """

    seen: list[AgentDeps] | None = None
    """Where each call records the deps it received - the only place the deps a
    delegation actually ran with are observable."""

    pause: float = 0
    """How long the call holds the delegation open, for a test that steers or
    cancels one while it is running."""

    on_call: Callable[[RunContext[AgentDeps]], str] | None = None

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        async def ping(ctx: RunContext[AgentDeps]) -> str:
            """Answer, so a model with something to call has something to call."""
            if self.seen is not None:
                self.seen.append(ctx.deps)
            if self.pause:
                await anyio.sleep(self.pause)
            return "pong" if self.on_call is None else self.on_call(ctx)

        return FunctionToolset([ping], id="pinging")


def delegate_agent(
    model: FunctionModel | TestModel,
    seen: list[AgentDeps] | None = None,
    *,
    gated: bool = False,
    on_call: Callable[[RunContext[AgentDeps]], str] | None = None,
    pause: float = 0,
) -> Callable[[], PydanticAgent[Any, Any]]:
    """A build closure like the runner's.

    `output_type` is `[str, DeferredToolRequests]` because that is what
    `app.agents.factory.build_agent` gives every agent this platform builds,
    delegates included - and it is what decides how a suspended delegation is
    reported: with it, a parked call ends the child's run with the requests as its
    output rather than raising, which is the route the library reports as
    `DEFERRED`. A delegate agent built here as plain `str` would exercise a
    failure mode no published delegate can reach.

    `gated` puts the real approval gate in front of the delegate's tool, which is
    how a delegate whose work needs a person is reached.
    """

    def build_it() -> PydanticAgent[Any, Any]:
        pinging = Pinging(seen=seen, pause=pause, on_call=on_call)
        # Stamped the way `app.agents.capabilities.build` stamps it, because that
        # is what puts `capability_id` on every tool definition the capability
        # contributes - and the gate keys on exactly that.
        pinging.id = "pinging"
        return PydanticAgent(
            model,
            system_prompt="You research.",
            output_type=[str, DeferredToolRequests],
            capabilities=(
                [ApprovalGate(required_tool_names=frozenset({"ping"})), pinging]
                if gated
                else [pinging]
            ),
        )

    return build_it


def a_delegate(
    *,
    model: FunctionModel | TestModel | None = None,
    max_steps: int | None = None,
    preferred_mode: str | None = None,
    agent_id: UUID | None = None,
    agent_version_id: UUID | None = None,
    collection_names: tuple[str, ...] = (),
    seen: list[AgentDeps] | None = None,
    gated: bool = False,
    on_call: Callable[[RunContext[AgentDeps]], str] | None = None,
    pause: float = 0,
) -> ResolvedSubagent:
    return ResolvedSubagent(
        name="researcher",
        description="Researches a topic and cites its sources.",
        build=delegate_agent(
            model if model is not None else answering(),
            seen,
            gated=gated,
            on_call=on_call,
            pause=pause,
        ),
        max_steps=max_steps,
        preferred_mode=preferred_mode,  # type: ignore[arg-type] - a Literal, spelt as a str here
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        collection_names=collection_names,
    )


class Recorder:
    """Stands in for the runner, which writes a child run row and answers with its id."""

    def __init__(self, run_id: UUID | None = None) -> None:
        self.outcomes: list[DelegationOutcome] = []
        self.run_id = run_id

    async def __call__(self, outcome: DelegationOutcome) -> UUID | None:
        self.outcomes.append(outcome)
        return self.run_id


class Sink:
    """Stands in for a surface that can show a delegation while it happens."""

    def __init__(self) -> None:
        self.frames: list[SubagentEvent] = []

    async def __call__(self, frame: SubagentEvent) -> None:
        self.frames.append(frame)

    @property
    def kinds(self) -> list[str]:
        return [frame.kind for frame in self.frames]


def a_runtime(
    *delegates: ResolvedSubagent,
    ledger: SpendLedger | None = None,
    record: Callable[[DelegationOutcome], Awaitable[UUID | None]] | None = None,
    depth_remaining: int = 1,
) -> SubagentRuntime:
    return SubagentRuntime(
        subagents=delegates, record=record, depth_remaining=depth_remaining, ledger=ledger
    )


def a_capability(runtime: SubagentRuntime, config: dict[str, Any] | None = None) -> Delegation:
    """The capability as the factory builds it, through the registry."""
    built = build(
        [CapabilityBinding(capability_id="subagents", config=config or {})],
        resources={SUBAGENT_RUNTIME_RESOURCE: runtime},
    )
    capability = built[0]
    assert isinstance(capability, Delegation)
    return capability


class Approvals:
    """Stands in for the run's approval channel, which parks and writes a row.

    Records what it was asked and answers `ApprovalPending`, exactly as
    `ApprovalChannel` does on a first ask. Counting the asks is the point: each
    one is a database write on the session the whole request shares.
    """

    def __init__(self) -> None:
        self.asked: list[ApprovalRequest] = []

    async def __call__(self, request: ApprovalRequest) -> ApprovalPending:
        self.asked.append(request)
        return ApprovalPending()


def a_context(
    sink: Sink | None = None,
    approvals: Approvals | None = None,
    *,
    run: str = "run-1",
) -> RunContext[AgentDeps]:
    """A parent run, with an organization, a run id and collections of its own.

    All three matter to what a delegation inherits: the first two travel down to
    the delegate (the run id keys the workspace they share), and the collections
    deliberately do not.

    `run` is Pydantic AI's own run id, which is what the library scopes a task
    handle to - so a second value is how "another run's task" is spelt.
    """
    return RunContext(
        deps=AgentDeps(
            organization_id=uuid4(),
            run_id=uuid4(),
            kb_collection_names=["kb_only_the_parent_may_read"],
            subagent_events=sink,
            request_approval=approvals,
        ),
        model=TestModel(),
        usage=RunUsage(),
        run_id=run,
    )


async def call_tool(
    capability: Delegation, ctx: RunContext[AgentDeps], tool: str, args: dict[str, Any]
) -> Any:
    """Call one of the capability's tools the way the model does, through the toolset."""
    toolset = capability.get_toolset()
    assert toolset is not None
    tools = await toolset.get_tools(ctx)
    return await toolset.call_tool(tool, args, ctx, tools[tool])


def task_id_in(answer: str) -> str:
    """The task id a background delegation reported, read the way a model reads it."""
    found = re.search(r"Task ID: (\w+)", answer)
    assert found is not None, answer
    return found.group(1)


async def ends_the_run(capability: Delegation, ctx: RunContext[AgentDeps]) -> str:
    """Finish the run the way Pydantic AI does, and answer with what it answered.

    Anything still delegating is cancelled and awaited here - by the library's own
    `wrap_run`, which this capability defers to - so a test that leaves a
    background delegation running without this leaves an asyncio task behind.
    """

    async def handler() -> str:
        return "the parent answered"

    return await capability.wrap_run(ctx, handler=handler)


async def delegate_to(capability: Delegation, ctx: RunContext[AgentDeps], **args: Any) -> Any:
    """Delegate to `researcher`, with whatever the model would have said about it."""
    return await call_tool(
        capability,
        ctx,
        "task",
        {"description": "find the price", "subagent_type": "researcher", **args},
    )


class TestAttaching:
    """A capability with no delegates must not exist at all."""

    def test_without_a_resolved_runtime_there_is_no_capability(self):
        """A preview, or a unit test: nothing resolved a delegation tree.

        Seven tools that can only refuse are worse than none - they are context
        the model pays for on every turn, and it keeps trying them.
        """
        assert build([CapabilityBinding(capability_id="subagents")]) == []

    def test_a_runtime_with_no_delegates_attaches_nothing_either(self):
        assert (
            build(
                [CapabilityBinding(capability_id="subagents")],
                resources={SUBAGENT_RUNTIME_RESOURCE: a_runtime()},
            )
            == []
        )

    def test_a_resolved_delegate_is_offered_to_the_model(self):
        capability = a_capability(a_runtime(a_delegate()))

        assert "researcher" in capability.get_instructions()
        assert "Researches a topic and cites its sources." in capability.get_instructions()

    def test_the_instructions_state_the_ceiling_the_model_will_hit(self):
        """A limit the model only learns about by being refused is a wasted turn."""
        instructions = a_capability(
            a_runtime(a_delegate()), {"mode": "async", "max_fanout": 2}
        ).get_instructions()

        assert "2 delegations run at once" in instructions
        assert "background" in instructions

    def test_a_binding_with_no_config_at_all_gets_the_defaults(self):
        """The builder is called with `config=None` by the registry's drift test."""
        capability = get("subagents").builder(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id="subagents"),
                config=None,
                resources={SUBAGENT_RUNTIME_RESOURCE: a_runtime(a_delegate())},
            )
        )

        assert isinstance(capability, Delegation)
        assert capability.journal.max_fanout == SubagentsConfig().max_fanout

    async def test_the_declared_tools_are_the_ones_the_model_is_offered(self):
        """Minus the two dynamic entry points, which are declared and not wired.

        Declared because a tool absent from `tools=` cannot be gated by the
        approval policy or renamed by a binding. Not wired because the library
        would build such a specialist itself, on its own default model - outside
        this deployment's catalog, vault and budget guard. `allow_dynamic`
        therefore changes nothing yet, and the README says so.
        """
        capability = a_capability(a_runtime(a_delegate()), {"allow_dynamic": True})
        toolset = capability.get_toolset()
        assert toolset is not None

        offered = frozenset(await toolset.get_tools(a_context()))

        assert offered == get("subagents").tool_ids - {"create_agent", "delegate"}

    async def test_the_model_reads_exactly_what_the_catalog_declares(self):
        """The other half of declaring the tools: the text has to be the same text.

        The Builder offers approval against these descriptions and the model
        decides to call against them, so two copies drift silently. The library
        appends the delegate list to `task`'s description unless told otherwise -
        which would make the catalog's copy a paraphrase, and repeat a list the
        instructions already carry.
        """
        capability = a_capability(a_runtime(a_delegate()))
        toolset = capability.get_toolset()
        assert toolset is not None
        declared = {tool.id: tool.description for tool in get("subagents").tools}

        offered = await toolset.get_tools(a_context())

        assert {name: tool.tool_def.description for name, tool in offered.items()} == {
            name: declared[name] for name in offered
        }

    def test_the_toolset_is_built_once_so_the_journal_is_not_restarted(self):
        capability = a_capability(a_runtime(a_delegate()))

        assert capability.get_toolset() is capability.get_toolset()


class TestRecording:
    """What a delegation cost, measured as the run ledger's growth across it."""

    async def test_a_delegation_records_what_the_ledger_grew_by(self):
        ledger = SpendLedger()
        recorder = Recorder(run_id=uuid4())
        agent_id, version_id = uuid4(), uuid4()
        capability = a_capability(
            a_runtime(
                a_delegate(
                    model=answering(ledger=ledger),
                    agent_id=agent_id,
                    agent_version_id=version_id,
                ),
                ledger=ledger,
                record=recorder,
            )
        )

        answer = await delegate_to(capability, a_context())

        assert "found it" in answer
        (outcome,) = recorder.outcomes
        assert outcome.status == "completed"
        assert outcome.cost_usd == ENTRY.cost_usd
        assert (outcome.input_tokens, outcome.output_tokens) == (7, 3)
        assert (outcome.agent_id, outcome.agent_version_id) == (agent_id, version_id)
        assert outcome.error is None

    async def test_only_this_delegation_s_share_of_the_ledger_is_attributed(self):
        """The delta, not the total: the parent has already spent before it delegates."""
        ledger = SpendLedger()
        ledger.entries.append(ENTRY)
        recorder = Recorder()
        capability = a_capability(
            a_runtime(a_delegate(model=answering(ledger=ledger)), ledger=ledger, record=recorder)
        )

        await delegate_to(capability, a_context())

        assert recorder.outcomes[0].cost_usd == ENTRY.cost_usd
        assert ledger.total_usd == ENTRY.cost_usd * 2

    async def test_without_a_ledger_a_delegation_reports_zero_rather_than_guessing(self):
        """A preview meters nothing, and zero is the honest answer there."""
        recorder = Recorder()
        capability = a_capability(a_runtime(a_delegate(), record=recorder))

        await delegate_to(capability, a_context())

        (outcome,) = recorder.outcomes
        assert (outcome.cost_usd, outcome.input_tokens, outcome.output_tokens) == (Decimal(0), 0, 0)

    async def test_a_run_with_no_recorder_still_delegates(self):
        """No database to write a child row to is not a reason to refuse the work."""
        capability = a_capability(a_runtime(a_delegate()))

        assert "found it" in await delegate_to(capability, a_context())

    async def test_a_failed_delegation_is_recorded_with_its_error(self):
        """A delegation that cost money and delivered nothing is the one worth recording."""
        ledger = SpendLedger()
        recorder = Recorder()
        capability = a_capability(
            a_runtime(a_delegate(model=looping(), max_steps=1), ledger=ledger, record=recorder)
        )

        with pytest.raises(UsageLimitExceeded):
            await delegate_to(capability, a_context())

        (outcome,) = recorder.outcomes
        assert outcome.status == "failed"
        assert outcome.error is not None and "usage limit" in outcome.error

    async def test_a_delegate_the_runtime_never_resolved_records_nothing(self):
        """The library refuses the name; no delegate ran, so there is no outcome."""
        recorder = Recorder()
        capability = a_capability(a_runtime(a_delegate(), record=recorder))

        answer = await delegate_to(capability, a_context(), subagent_type="inventor")

        assert "Unknown subagent" in answer
        assert recorder.outcomes == []

    async def test_a_delegation_refused_before_it_started_records_nothing(self):
        """A `chat_trace_id` the library does not know: a task id, but no task."""
        recorder = Recorder()
        capability = a_capability(a_runtime(a_delegate(), record=recorder))

        answer = await delegate_to(capability, a_context(), chat_trace_id="never-seen")

        assert "no saved conversation" in answer
        assert recorder.outcomes == []


class TestStepLimits:
    """The only thing between a delegation and a loop that delegates to a loop."""

    async def test_a_delegate_s_max_steps_becomes_its_request_limit(self):
        capability = a_capability(a_runtime(a_delegate(model=looping(), max_steps=1)))

        with pytest.raises(UsageLimitExceeded, match="request_limit of 1"):
            await delegate_to(capability, a_context())

    async def test_a_delegate_with_no_max_steps_gets_the_platform_default(self):
        """One constant for a delegation and a top-level run, so raising it raises both."""
        runtime = a_runtime(a_delegate())
        capability = a_capability(runtime)
        await delegate_to(capability, a_context())

        limits = capability.journal.tasks.get_handle
        assert limits is not None  # the delegation ran; the ceiling below is the point
        assert _limits(runtime).request_limit == DEFAULT_MAX_STEPS

    async def test_a_delegate_nobody_resolved_gets_the_default_too(self):
        """The library's general-purpose subagent, which no runtime resolved."""
        assert _limits(a_runtime(a_delegate()), name="general-purpose").request_limit == (
            DEFAULT_MAX_STEPS
        )


def _limits(runtime: SubagentRuntime, *, name: str = "researcher") -> UsageLimits:
    """The ceiling the library would resolve for one delegation.

    Reached through the capability rather than the private factory: what matters
    is that the library is handed a factory at all, and that it answers per
    delegate.
    """
    capability = a_capability(runtime)
    factory = capability.wrapped.usage_limits  # ty: ignore[unresolved-attribute]
    assert callable(factory)
    limits = factory(a_context(), SubAgentConfig(name=name, description="", instructions=""))
    assert isinstance(limits, UsageLimits)
    return limits


class TestFanout:
    """How many agents one turn may start."""

    async def test_a_delegation_beyond_the_ceiling_is_refused_readably(self):
        """A tool result the model can act on, not an exception that ends the run."""
        recorder = Recorder()
        capability = a_capability(a_runtime(a_delegate(), record=recorder), {"max_fanout": 1})
        ctx = a_context()
        answers: list[str] = []

        async def once() -> None:
            answers.append(await delegate_to(capability, ctx))

        async with anyio.create_task_group() as group:
            group.start_soon(once)
            group.start_soon(once)

        refusals = [answer for answer in answers if answer.startswith("Refused:")]
        assert len(refusals) == 1
        assert "1 delegations at a time" in refusals[0]
        assert "check_task" in refusals[0]
        assert len(recorder.outcomes) == 1

    async def test_a_finished_delegation_stops_occupying_a_slot(self):
        capability = a_capability(a_runtime(a_delegate()), {"max_fanout": 1})
        ctx = a_context()

        first = await delegate_to(capability, ctx)
        second = await delegate_to(capability, ctx)

        assert "found it" in first
        assert "found it" in second
        assert capability.journal.in_flight() == 0


class TestMode:
    """Whether a delegation blocks the run, and who decides."""

    async def test_the_spec_s_mode_wins_over_the_model_s_argument(self):
        """`mode` defaults to sync in the tool schema, so a model that said nothing
        and a model that chose sync are the same call. The author's choice was
        reviewed; the model's was not."""
        capability = a_capability(a_runtime(a_delegate()), {"mode": "async"})
        ctx = a_context()

        answer = await delegate_to(capability, ctx, mode="sync")

        assert "Task started in background" in answer
        await ends_the_run(capability, ctx)

    async def test_a_delegate_s_preferred_mode_overrides_the_agent_s(self):
        capability = a_capability(a_runtime(a_delegate(preferred_mode="async")), {"mode": "sync"})
        ctx = a_context()

        assert "Task started in background" in await delegate_to(capability, ctx)
        await ends_the_run(capability, ctx)

    async def test_auto_hands_the_decision_to_the_task_s_own_characteristics(self):
        """The one mode where what the model says about the work decides.

        Resolved before the delegation rather than left to the library, because the
        opening frame has to name the mode: a surface that tears its panel down on
        the parent's answer would otherwise drop a background delegate's last word.
        """
        capability = a_capability(a_runtime(a_delegate()), {"mode": "auto", "max_fanout": 10})
        ctx = a_context()

        quick = await delegate_to(capability, ctx, complexity="simple")
        long_running = await delegate_to(capability, ctx, complexity="complex")

        assert "found it" in quick
        assert "Task started in background" in long_running
        await ends_the_run(capability, ctx)


class TestBackgroundDelegations:
    """A delegation whose outcome arrives after the call that started it."""

    async def test_a_background_delegation_is_recorded_once_it_finishes(self):
        ledger = SpendLedger()
        recorder = Recorder()
        capability = a_capability(
            a_runtime(a_delegate(model=answering(ledger=ledger)), ledger=ledger, record=recorder),
            {"mode": "async"},
        )
        ctx = a_context()

        started = await delegate_to(capability, ctx)
        assert "found it" in await call_tool(
            capability, ctx, "wait_tasks", {"task_ids": [task_id_in(started)]}
        )

        # The next delegation settles whatever finished, which is also how a
        # finished background task stops occupying a fan-out slot.
        await delegate_to(capability, ctx)

        finished = [outcome for outcome in recorder.outcomes if outcome.status == "completed"]
        assert finished[0].cost_usd == ENTRY.cost_usd
        assert (finished[0].input_tokens, finished[0].output_tokens) == (7, 3)

        # What ends a real run, and what this test would otherwise leak: the
        # second delegation is still executing in a task nobody awaits.
        await ends_the_run(capability, ctx)

    async def test_one_that_is_still_running_keeps_its_slot(self):
        """The sweep before each delegation must not close the books early.

        A delegation recorded while it is still running would report a status it
        has not reached and a cost it has not finished spending - and it would free
        the fan-out slot it is still occupying.
        """
        recorder = Recorder()
        capability = a_capability(
            a_runtime(a_delegate(model=blocking()), record=recorder),
            {"mode": "async", "max_fanout": 2},
        )
        ctx = a_context()

        await delegate_to(capability, ctx)
        await delegate_to(capability, ctx)

        assert recorder.outcomes == []
        assert capability.journal.in_flight() == 2

        await ends_the_run(capability, ctx)
        assert [outcome.status for outcome in recorder.outcomes] == ["cancelled", "cancelled"]

    async def test_the_end_of_the_run_records_one_that_never_finished(self):
        """The library cancels every background task when the run ends. Without
        this sweep the spend of a delegation nobody collected is attributed to
        nothing at all."""
        recorder = Recorder()
        sink = Sink()
        capability = a_capability(
            a_runtime(a_delegate(model=looping()), record=recorder), {"mode": "async"}
        )
        ctx = a_context(sink)
        await delegate_to(capability, ctx)

        assert await ends_the_run(capability, ctx) == "the parent answered"
        assert [outcome.status for outcome in recorder.outcomes] == ["cancelled"]
        assert sink.kinds[-1] == "subagent_complete"

    async def test_nothing_is_still_running_once_the_run_has_ended(self):
        """The guarantee every test in this file depends on, asserted once.

        `wrap_run` is the only thing between a background delegation and an
        asyncio task that keeps working against a torn-down request - deps whose
        session is closed, a socket that has gone. Counting the loop's tasks
        proves the cancellation happened rather than trusting that awaiting the
        library's finalizer implies it.
        """
        capability = a_capability(
            a_runtime(a_delegate(model=blocking())), {"mode": "async", "max_fanout": 3}
        )
        ctx = a_context()
        before = len(asyncio.all_tasks())

        for _ in range(3):
            await delegate_to(capability, ctx)
        assert len(asyncio.all_tasks()) == before + 3

        await ends_the_run(capability, ctx)

        assert capability.journal.tasks.list_active_tasks() == []
        assert len(asyncio.all_tasks()) == before


class TestTaskLifecycle:
    """Reading, steering and stopping a delegation that is already running.

    The library owns all six tools - this platform declares them, gates the three
    that act, and passes every one of them straight through. What is pinned here is
    that each does what the capability catalog says it does, because a description
    the model reads and a behaviour nobody exercised is how an orchestrator learns
    to poll an id that will never resolve.
    """

    async def test_check_task_reports_a_finished_delegation_in_full(self):
        capability = a_capability(a_runtime(a_delegate()), {"mode": "async"})
        ctx = a_context()

        task_id = task_id_in(await delegate_to(capability, ctx))
        await call_tool(capability, ctx, "wait_tasks", {"task_ids": [task_id]})
        reported = await call_tool(capability, ctx, "check_task", {"task_id": task_id})

        assert f"Task: {task_id}" in reported
        assert "Status: completed" in reported
        assert "Result: found it" in reported

    async def test_check_task_on_an_id_this_run_did_not_start_is_not_found(self):
        """Task ids are short and appear in tool output, so admitting another
        run's id would let one run read - and cancel - another's work."""
        capability = a_capability(a_runtime(a_delegate(model=blocking())), {"mode": "async"})
        ctx = a_context()
        task_id = task_id_in(await delegate_to(capability, ctx))

        answer = await call_tool(
            capability, a_context(run="somebody-elses-run"), "check_task", {"task_id": task_id}
        )

        assert answer == f"Error: Task '{task_id}' not found"
        await ends_the_run(capability, ctx)

    async def test_wait_tasks_truncates_a_long_answer_and_says_where_the_rest_is(self):
        """A silent cut reads to an orchestrator like a specialist that stopped
        mid-sentence, so it re-delegates work it has already been handed half of
        (subagents-pydantic-ai#55). The marker is what prevents that, and
        `max_result_chars` is the author's control over how much of five
        specialists' work arrives in one turn's context."""
        answer = "x" * 900
        capability = a_capability(
            a_runtime(a_delegate(model=answering(answer))),
            {"mode": "async", "max_result_chars": 200},
        )
        ctx = a_context()

        task_id = task_id_in(await delegate_to(capability, ctx))
        listed = await call_tool(capability, ctx, "wait_tasks", {"task_ids": [task_id]})

        assert "x" * 200 in listed
        assert "x" * 201 not in listed
        assert "showing 200 of 900 characters" in listed
        assert f"check_task('{task_id}')" in listed
        # The other half of the promise the marker makes: nothing was lost.
        assert answer in await call_tool(capability, ctx, "check_task", {"task_id": task_id})

    async def test_wait_tasks_leaves_a_short_answer_alone(self):
        """The budget is a ceiling, not a formatter: an answer that fits arrives
        whole, with nothing pointing anywhere."""
        capability = a_capability(a_runtime(a_delegate()), {"mode": "async"})
        ctx = a_context()

        listed = await call_tool(
            capability,
            ctx,
            "wait_tasks",
            {"task_ids": [task_id_in(await delegate_to(capability, ctx))]},
        )

        assert "found it" in listed
        assert "truncated" not in listed

    async def test_wait_tasks_says_which_ids_it_could_not_find(self):
        """An id that resolves to nothing is neither finished nor running, and
        counting it as running is how a model polls forever."""
        capability = a_capability(a_runtime(a_delegate()), {"mode": "async"})
        ctx = a_context()

        listed = await call_tool(capability, ctx, "wait_tasks", {"task_ids": ["never-existed"]})

        assert "1 not found" in listed
        assert "still running" not in listed

    async def test_list_active_tasks_names_what_is_running_and_says_when_nothing_is(self):
        capability = a_capability(
            a_runtime(a_delegate(model=blocking())), {"mode": "async", "max_fanout": 2}
        )
        ctx = a_context()

        assert await call_tool(capability, ctx, "list_active_tasks", {}) == (
            "No active background tasks."
        )
        task_id = task_id_in(await delegate_to(capability, ctx))
        listed = await call_tool(capability, ctx, "list_active_tasks", {})

        assert task_id in listed
        assert "researcher" in listed
        await ends_the_run(capability, ctx)

    async def test_steering_a_running_delegation_reaches_it_before_its_next_request(self):
        """The point of steering rather than cancelling: partial progress is kept.

        The message is asserted through the delegate's own answer, not through the
        tool's acknowledgement - "delivered" is what the bus says, and what matters
        is that the specialist read it.
        """
        capability = a_capability(
            a_runtime(a_delegate(model=steerable(), pause=0.1)), {"mode": "async"}
        )
        ctx = a_context()
        task_id = task_id_in(await delegate_to(capability, ctx))

        steered = await call_tool(
            capability,
            ctx,
            "send_message_to_subagent",
            {"task_id": task_id, "message": "prices in EUR, not USD"},
        )
        listed = await call_tool(capability, ctx, "wait_tasks", {"task_ids": [task_id]})

        assert f"Message delivered to task '{task_id}'" in steered
        assert "prices in EUR, not USD" in listed

    async def test_steering_a_delegation_that_already_answered_is_refused_readably(self):
        capability = a_capability(a_runtime(a_delegate()), {"mode": "async"})
        ctx = a_context()
        task_id = task_id_in(await delegate_to(capability, ctx))
        await call_tool(capability, ctx, "wait_tasks", {"task_ids": [task_id]})

        answer = await call_tool(
            capability, ctx, "send_message_to_subagent", {"task_id": task_id, "message": "faster"}
        )

        assert "is not accepting messages" in answer
        assert "Steering only works for running" in answer

    async def test_a_soft_cancel_stops_the_delegate_at_a_clean_boundary(self):
        """Cooperative: the cancel event is polled between graph nodes, so the
        specialist stops having finished whatever step it was on - and the
        delegation is still recorded, because it spent money getting there."""
        recorder = Recorder()
        capability = a_capability(
            a_runtime(a_delegate(model=looping(), pause=0.05), record=recorder), {"mode": "async"}
        )
        ctx = a_context()
        task_id = task_id_in(await delegate_to(capability, ctx))

        assert f"Cancellation requested for task '{task_id}'" in await call_tool(
            capability, ctx, "soft_cancel_task", {"task_id": task_id}
        )
        await ends_the_run(capability, ctx)

        assert [outcome.status for outcome in recorder.outcomes] == ["cancelled"]

    async def test_a_hard_cancel_stops_it_immediately_and_it_is_still_recorded(self):
        """The destructive one, which is why it needs a person: work that was paid
        for and will not be delivered."""
        recorder = Recorder()
        sink = Sink()
        capability = a_capability(
            a_runtime(a_delegate(model=blocking()), record=recorder), {"mode": "async"}
        )
        ctx = a_context(sink)
        task_id = task_id_in(await delegate_to(capability, ctx))

        assert await call_tool(capability, ctx, "hard_cancel_task", {"task_id": task_id}) == (
            f"Task '{task_id}' has been cancelled"
        )
        await ends_the_run(capability, ctx)

        assert [outcome.status for outcome in recorder.outcomes] == ["cancelled"]
        assert sink.frames[-1].kind == "subagent_complete"
        assert capability.journal.in_flight() == 0

    @pytest.mark.parametrize("tool", ["soft_cancel_task", "hard_cancel_task"])
    async def test_cancelling_a_delegation_that_already_finished_explains_itself(self, tool: str):
        """ "Not found" would invite the model to conclude the work was lost, when
        its result is still there to read."""
        capability = a_capability(a_runtime(a_delegate()), {"mode": "async"})
        ctx = a_context()
        task_id = task_id_in(await delegate_to(capability, ctx))
        await call_tool(capability, ctx, "wait_tasks", {"task_ids": [task_id]})

        answer = await call_tool(capability, ctx, tool, {"task_id": task_id})

        assert "no longer running" in answer
        assert f"check_task('{task_id}')" in answer


class TestApprovalInsideADelegation:
    """A delegate whose tool needs a person, in each mode.

    The two halves are genuinely different products. A *sync* delegation holds the
    parent's tool call, so a parked call suspends the parent too and the whole run
    lands in the approvals queue - which is the supported shape, and what makes a
    gated tool inside a delegate usable at all. A *background* delegation has
    already returned its task id, so there is no caller left to park: the library
    says as much and this platform refuses before the ask, because the ask itself
    is a database write on a session the parent is still using.
    """

    async def test_a_sync_delegation_can_park_the_run_on_its_delegate_s_approval(self):
        approvals = Approvals()
        capability = a_capability(a_runtime(a_delegate(model=one_tool_call(), gated=True)))
        ctx = a_context(approvals=approvals)

        with pytest.raises(ApprovalRequired):
            await delegate_to(capability, ctx)

        assert [request.tool_name for request in approvals.asked] == ["ping"]

    async def test_a_background_delegation_never_reaches_the_approval_queue(self):
        """The refusal that keeps a background delegate off the request's session.

        `AgentDeps.request_approval` closes over `ApprovalService`, which holds the
        `AsyncSession` the whole run shares and which is not concurrency-safe - and
        a background delegation outlives the tool call that started it. So the
        channel is not passed down, the gate takes the branch it was already
        written for, and the delegate is told a person could not be asked instead
        of writing a row from a task nobody is waiting on.
        """
        approvals = Approvals()
        seen: list[AgentDeps] = []
        recorder = Recorder()
        capability = a_capability(
            a_runtime(
                a_delegate(model=one_tool_call(text=None), gated=True, seen=seen), record=recorder
            ),
            {"mode": "async"},
        )
        ctx = a_context(approvals=approvals)

        task_id = task_id_in(await delegate_to(capability, ctx))
        listed = await call_tool(capability, ctx, "wait_tasks", {"task_ids": [task_id]})
        await ends_the_run(capability, ctx)

        assert approvals.asked == [], "a background delegation must not write an approval row"
        assert seen == [], "the gate must refuse before the tool body runs"
        assert "COMPLETED" in listed
        assert "cannot ask anyone to approve it" in listed
        assert [outcome.status for outcome in recorder.outcomes] == ["completed"]
        assert capability.journal.in_flight() == 0

    @pytest.mark.parametrize("mode", ["sync", "async"])
    async def test_only_a_background_delegate_is_handed_no_approval_channel(self, mode: str):
        """The substitution itself, on a delegate with nothing gated.

        Both halves in one place because the danger is symmetric: leaving the
        channel on a background delegation writes a row from a task nobody is
        waiting on, and taking it off a sync one would make every gated tool
        inside a specialist unusable - which is the shape this platform supports.
        """
        seen: list[AgentDeps] = []
        approvals = Approvals()
        capability = a_capability(
            a_runtime(a_delegate(model=one_tool_call(), seen=seen)), {"mode": mode}
        )
        ctx = a_context(approvals=approvals)

        answer = await delegate_to(capability, ctx)
        if mode == "async":
            await call_tool(capability, ctx, "wait_tasks", {"task_ids": [task_id_in(answer)]})
            await ends_the_run(capability, ctx)

        assert [deps.request_approval for deps in seen] == [None if mode == "async" else approvals]

    async def test_a_background_delegation_that_suspends_anyway_fails_readably(self):
        """The library's contract, asserted rather than assumed.

        A tool can defer a call without going through the approval gate at all, and
        the library reports that as `DEFERRED` with a message naming the rule. This
        platform records it as `failed`: reading it as "still going" - which is what
        `_RESOLVED` alone did - attributed the spend to nothing, never released the
        fan-out slot, and left the panel a surface had opened permanently open.
        """
        recorder = Recorder()
        sink = Sink()

        def defer(_ctx: RunContext[AgentDeps]) -> str:
            raise ApprovalRequired

        capability = a_capability(
            a_runtime(a_delegate(model=one_tool_call(), on_call=defer), record=recorder),
            {"mode": "async"},
        )
        ctx = a_context(sink)
        task_id = task_id_in(await delegate_to(capability, ctx))
        await call_tool(capability, ctx, "wait_tasks", {"task_ids": [task_id]})

        await ends_the_run(capability, ctx)

        (outcome,) = recorder.outcomes
        assert outcome.status == "failed"
        assert outcome.error is not None
        assert "cannot run in the background" in outcome.error
        assert "mode='sync'" in outcome.error
        assert capability.journal.in_flight() == 0
        assert sink.frames[-1].kind == "subagent_complete"

    async def test_a_sync_delegation_that_suspends_is_not_recorded_as_an_outcome(self):
        """The same status, the opposite meaning. Nothing went wrong and the answer
        is still coming: the signal parks the parent run, and the resumed run
        delegates again - so a row written here would describe unfinished work and
        then be double-counted."""
        recorder = Recorder()

        def defer(_ctx: RunContext[AgentDeps]) -> str:
            raise ApprovalRequired

        capability = a_capability(
            a_runtime(a_delegate(model=one_tool_call(), on_call=defer), record=recorder)
        )

        with pytest.raises(ApprovalRequired):
            await delegate_to(capability, a_context())

        assert recorder.outcomes == []


class TestNarration:
    """What a surface hears while a delegation runs."""

    async def test_the_frames_arrive_labelled_and_in_order(self):
        sink = Sink()
        recorder = Recorder(run_id=uuid4())
        capability = a_capability(a_runtime(a_delegate(), record=recorder))

        await delegate_to(capability, a_context(sink))

        assert sink.kinds[0] == "subagent_start"
        assert sink.kinds[-1] == "subagent_complete"
        assert "subagent_text_delta" in sink.kinds
        assert {frame.subagent for frame in sink.frames} == {"researcher"}
        assert len({frame.task_id for frame in sink.frames}) == 1
        assert {frame.depth for frame in sink.frames} == {0}
        assert sink.frames[-1].run_id == recorder.run_id

    async def test_a_delegation_that_produced_no_events_still_opens_its_panel(self):
        """A `subagent_complete` for a panel nobody opened is a delegation a
        reader never learns about."""
        sink = Sink()
        capability = a_capability(a_runtime(a_delegate(model=looping(), max_steps=1)))

        with pytest.raises(UsageLimitExceeded):
            await delegate_to(capability, a_context(sink))

        assert sink.kinds[0] == "subagent_start"
        assert sink.kinds[-1] == "subagent_complete"
        assert sink.frames[-1].status == "failed"

    async def test_a_surface_that_cannot_show_a_delegation_is_not_an_error(self):
        """Most surfaces cannot: an API call, a schedule, a Slack mention."""
        recorder = Recorder()
        capability = a_capability(a_runtime(a_delegate(), record=recorder))

        assert "found it" in await delegate_to(capability, a_context())
        assert len(recorder.outcomes) == 1

    def test_a_delegation_this_capability_did_not_start_streams_nothing(self):
        """The library resolves a handler for every delegation, including one
        started by an entry point this toolset does not intercept. An unlabelled
        frame is worse than none - no surface can tell whose panel it belongs
        to."""
        capability = a_capability(a_runtime(a_delegate()))

        assert (
            capability.journal.stream_for(
                a_context(Sink()),
                SubAgentConfig(name="researcher", description="", instructions=""),
                "task-1",
            )
            is None
        )

    async def test_the_delegate_s_own_tool_calls_are_reported(self):
        """The delegate's tools, not the parent's - the only place a reader learns
        a specialist searched something the parent cannot even see."""
        sink = Sink()
        capability = a_capability(a_runtime(a_delegate(model=looping(), max_steps=2)))

        with pytest.raises(UsageLimitExceeded):
            await delegate_to(capability, a_context(sink))

        assert "subagent_tool_call" in sink.kinds
        assert "subagent_tool_result" in sink.kinds
        calls = [frame for frame in sink.frames if frame.kind == "subagent_tool_call"]
        assert calls[0].tool_name == "ping"


class TestDelegateDeps:
    """What a delegation actually runs with, which is not what its build produced."""

    async def test_a_delegate_searches_the_collections_its_own_spec_bound(self):
        """The failure this pins is silent (agenticos#166).

        The library clones the *parent's* deps for every delegation, so the
        `AgentDeps` the runner built for the delegate - collections included - is
        discarded before the delegate's first request. Left alone, a specialist
        bound to a collection answers "No active knowledge bases selected" to every
        search: correctly configured, cleanly published, and unable to read the one
        thing it exists to read.
        """
        seen: list[AgentDeps] = []
        capability = a_capability(
            a_runtime(
                a_delegate(
                    model=one_tool_call(), collection_names=("kb_the_delegate_may_read",), seen=seen
                )
            )
        )
        ctx = a_context()

        await delegate_to(capability, ctx)

        assert [deps.kb_collection_names for deps in seen] == [["kb_the_delegate_may_read"]]

    async def test_a_delegate_does_not_inherit_the_parent_s_collections(self):
        """The other half, and the reason the clone drops them: handing a
        specialist the parent's collections is a grant nobody made."""
        seen: list[AgentDeps] = []
        capability = a_capability(a_runtime(a_delegate(model=one_tool_call(), seen=seen)))
        ctx = a_context()

        await delegate_to(capability, ctx)

        assert ctx.deps.kb_collection_names == ["kb_only_the_parent_may_read"]
        assert seen[0].kb_collection_names == []

    async def test_everything_else_on_the_deps_still_travels_down(self):
        """Substituting the collections must not cost the rest of the clone.

        The parent's `run_id` is the one that looks like a bug and is not: it keys
        the workspace session, so a researcher and a writer read each other's
        files. The channels are the parent's because a specialist that needs a
        person needs the person already waiting.
        """
        seen: list[AgentDeps] = []
        sink = Sink()
        capability = a_capability(
            a_runtime(a_delegate(model=one_tool_call(), seen=seen), depth_remaining=2)
        )
        ctx = a_context(sink)

        await delegate_to(capability, ctx)

        (deps,) = seen
        assert deps is not ctx.deps, "a fresh object, so concurrent specialists share nothing"
        assert deps.organization_id == ctx.deps.organization_id
        assert deps.run_id == ctx.deps.run_id
        assert deps.agent_id == ctx.deps.agent_id
        assert deps.subagent_events is sink


def _in_the_foreground() -> bool:
    """The `in_background` predicate for a sync delegation, spelt out.

    `_LazyAgent` takes it from the journal in production; the tests below drive
    the stand-in directly, where there is no delegation in flight to ask about.
    """
    return False


class TestLazyDelegate:
    """The stand-in the library compiles in place of a delegate's agent."""

    async def test_both_entry_points_substitute_the_deps(self):
        """`iter` is the path the library takes with retries on - its default - and
        `run` the one it takes with them off. A substitution on only the path in
        use today is one that disappears the day a config changes."""
        seen: list[AgentDeps] = []
        proxy = _LazyAgent(
            a_delegate(model=one_tool_call(), collection_names=("kb_x",), seen=seen),
            _in_the_foreground,
        )

        await proxy.run("go", deps=AgentDeps(kb_collection_names=["kb_the_parent_s"]))

        assert [deps.kb_collection_names for deps in seen] == [["kb_x"]]

    def test_the_agent_is_built_when_it_is_first_needed_and_then_reused(self):
        """A delegate the model never calls should cost nothing: building one
        resolves a model profile, assembles capabilities and instruments it."""
        builds = 0

        def build_it() -> PydanticAgent[Any, Any]:
            nonlocal builds
            builds += 1
            return PydanticAgent(TestModel(), system_prompt="x")

        proxy = _LazyAgent(
            ResolvedSubagent(name="researcher", description="R", build=build_it),
            _in_the_foreground,
        )
        assert builds == 0

        assert proxy.name is None and proxy.model is not None
        assert builds == 1


class TestApproval:
    """Which of these tools a person has to answer for."""

    def test_only_the_tools_that_act_on_running_work_need_a_person(self):
        """Delegating is not one of them, and that is the decision worth pinning.

        What a delegate *does* is gated by the delegate's own spec, through this
        same gate. Gating the delegation as well would ask somebody to approve it
        before the work that might need approving has even been proposed - and an
        author who does want that has one `tool_approval` override. Cancelling and
        steering are the opposite case: they destroy or redirect work already paid
        for.
        """
        spec = AgentSpec(name="Orchestrator", capabilities=[CapabilityBindingSpec(id="subagents")])

        assert approval_required_tools(spec) == {
            "send_message_to_subagent",
            "soft_cancel_task",
            "hard_cancel_task",
            # Not reachable yet, and gated for when they are: an agent nobody
            # published is what `allow_dynamic` exists to hold back.
            "create_agent",
            "delegate",
        }


class TestOtherTools:
    """The six tools that read or steer what a run already started."""

    async def test_they_pass_through_untouched(self):
        """Nothing here decides anything about them: they read and steer tasks this
        run already started, and the approval gate covers the two that act."""
        capability = a_capability(a_runtime(a_delegate()))

        answer = await call_tool(capability, a_context(), "list_active_tasks", {})

        assert isinstance(answer, str)
        assert capability.journal.in_flight() == 0


LABELS = FrameLabels(task_id="t-1", subagent="researcher", depth=1)


class TestFrames:
    """Translating a delegate's stream, event by event.

    Directly rather than through a run: a provider that sends a whole sentence in
    the opening event and one that streams it a token at a time produce different
    events for the same answer, and only one of them appears in a `TestModel` run.
    """

    @pytest.mark.parametrize(
        ("event", "kind", "text"),
        [
            (PartStartEvent(index=0, part=TextPart("hello")), "subagent_text_delta", "hello"),
            (
                PartStartEvent(index=0, part=ThinkingPart("weighing it")),
                "subagent_thinking_delta",
                "weighing it",
            ),
            (
                PartDeltaEvent(index=0, delta=TextPartDelta(content_delta=" world")),
                "subagent_text_delta",
                " world",
            ),
            (
                PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta="still")),
                "subagent_thinking_delta",
                "still",
            ),
        ],
    )
    def test_text_and_reasoning_become_deltas(self, event: AgentStreamEvent, kind: str, text: str):
        frame = frame_for(event, LABELS)

        assert frame is not None
        assert (frame.kind, frame.delta) == (kind, text)
        assert (frame.task_id, frame.subagent, frame.depth) == ("t-1", "researcher", 1)

    def test_a_tool_call_opens_a_row(self):
        frame = frame_for(
            FunctionToolCallEvent(part=ToolCallPart("search", {}, tool_call_id="c-1")), LABELS
        )

        assert frame is not None
        assert (frame.kind, frame.tool_name, frame.tool_call_id) == (
            "subagent_tool_call",
            "search",
            "c-1",
        )

    def test_a_tool_result_closes_it(self):
        frame = frame_for(
            FunctionToolResultEvent(
                part=ToolReturnPart(tool_name="search", content="ok", tool_call_id="c-1")
            ),
            LABELS,
        )

        assert frame is not None
        assert (frame.kind, frame.tool_name, frame.ok) == ("subagent_tool_result", "search", True)

    def test_a_tool_that_raised_is_marked_rather_than_dropped(self):
        frame = frame_for(
            FunctionToolResultEvent(
                part=RetryPromptPart(content="nope", tool_name="search", tool_call_id="c-1")
            ),
            LABELS,
        )

        assert frame is not None
        assert frame.ok is False

    def test_a_result_that_names_no_tool_still_reaches_the_panel(self):
        """`RetryPromptPart.tool_name` is optional, and a dropped result leaves a
        row open forever - which reads as a delegate still working on something
        that already failed."""
        frame = frame_for(
            FunctionToolResultEvent(part=RetryPromptPart(content="nope", tool_call_id="c-1")),
            LABELS,
        )

        assert frame is not None
        assert frame.tool_name == UNNAMED_TOOL

    @pytest.mark.parametrize(
        "event",
        [
            PartStartEvent(index=0, part=TextPart("")),
            PartStartEvent(index=0, part=ToolCallPart("search", {}, tool_call_id="c-1")),
            PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta=None)),
            PartDeltaEvent(index=0, delta=ToolCallPartDelta(args_delta="{")),
            FinalResultEvent(tool_name=None, tool_call_id=None),
        ],
    )
    def test_everything_a_panel_cannot_use_becomes_nothing(self, event: AgentStreamEvent):
        """Not an error: a run emits far more events than a panel can show, and
        each one forwarded is a socket write to show a reader nothing."""
        assert frame_for(event, LABELS) is None
