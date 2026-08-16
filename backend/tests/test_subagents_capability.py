"""The delegation capability - what it offers, what it refuses, what it records.

Delegation is the one capability whose failures are all quiet. A delegate that
runs but is never recorded spends real money against nothing; a fan-out ceiling
that does not bind lets one turn start a dozen agents; a mode nobody enforces
turns a blocking delegation into a background one whose answer arrives after the
run has ended. None of those look like errors, so each one is pinned here.

The background path adds three more of the same kind, and each has its own class:
a delegation nobody collects (`TestBackgroundDelegations`), a lifecycle tool whose
description promises something it does not do (`TestTaskLifecycle` - and
`TestAttaching`, for the one whose promise cannot be kept at all and which is
therefore not offered), and a delegate that stops for a person nobody can ask
(`TestApprovalInsideADelegation`). Cancellation is deliberately *not* here: the
cancel that matters arrives from outside the run, so it is asserted through the
surface that sends it, in
`tests/test_agent_session.py::TestStoppingATurnMidDelegation`.

Every model is `TestModel` or `FunctionModel`: a delegation is a whole second
agent run, and this suite would otherwise be the most expensive one in the
repository.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
from subagents_pydantic_ai import SubAgentConfig, TaskHandle, TaskManager, TaskStatus

from app.agents.capabilities import CapabilityBinding, CapabilityBuildContext, build, get
from app.agents.capabilities.approval import (
    ApprovalGate,
    ApprovalPending,
    ApprovalRequest,
    approval_required_tools,
)
from app.agents.capabilities.budget import BudgetExceeded, BudgetScope, SpendEntry, SpendLedger
from app.agents.capabilities.subagents import Delegation, SubagentsConfig
from app.agents.capabilities.subagents._capability import (
    BACKGROUND_LIFECYCLE_TOOLS,
    UNREACHABLE_TOOLS,
    _config_for,
    _LazyAgent,
)
from app.agents.capabilities.subagents._events import UNNAMED_TOOL, FrameLabels, frame_for
from app.agents.capabilities.subagents._journal import DelegationJournal
from app.agents.capabilities.subagents._toolset import DelegatingToolset
from app.agents.deps import AgentDeps
from app.agents.factory import DEFAULT_MAX_STEPS
from app.agents.spec import AgentSpec, CapabilityBindingSpec, DelegationMode
from app.agents.subagent_events import SubagentEvent, SubagentFinished
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

A fixed entry booked by the delegate's own model rather than a real price lookup:
the number under test is the *share* the journal attributes, and a share of an
unpriced model is zero however correct the attribution is.
"""

PARENT_REQUEST = SpendEntry(
    model_name="test", input_tokens=200, output_tokens=100, cost_usd=Decimal("0.05"), priced=True
)
"""One request the parent makes on its own account, while or after a delegate runs.

Deliberately not the same number as `ENTRY`, and ten of them are twice the whole
delegation: an assertion about whose spend is whose has to fail when the two are
confused, and equal numbers make that indistinguishable from arithmetic.
"""


def answering(text: str = "found it", *, ledger: SpendLedger | None = None) -> FunctionModel:
    """A model that answers once, spending into the run's ledger if there is one.

    Standing in for the budget guard, which is what records a real request. The
    delegate spends into the *parent's* ledger by construction - one ledger per
    run - and `book` is how the guard puts an entry into it, so it is how this
    spends too: booking is where the entry is stamped with the delegation that
    made it, and an entry appended around that is an entry attributed to the run's
    own agent.

    Both halves are supplied because a delegation on a surface that narrates it is
    *streamed*: the library resolves an event handler, which puts the delegate's
    run on `iter` rather than `run`, and a `FunctionModel` with no
    `stream_function` raises there.
    """

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if ledger is not None:
            ledger.book(ENTRY)
        return ModelResponse(parts=[TextPart(text)])

    async def stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        if ledger is not None:
            ledger.book(ENTRY)
        yield text

    return FunctionModel(respond, stream_function=stream)


def handing_on(to: str, *, ledger: SpendLedger) -> FunctionModel:
    """A model that delegates once and then answers with what came back.

    Two requests, both booked to whichever delegation is running when they are made
    - which is the whole point when this model is a *delegate's*: its own two
    requests are its own, and the third request the run makes is its delegate's.

    No `stream_function`, unlike `answering`: nothing here narrates, so no sink is
    handed down the tree, so the library resolves no event handler and drives every
    delegation through `run`. A streamed half would be a branch no test reaches.
    """

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        ledger.book(ENTRY)
        returned = _tool_results(messages)
        if returned:
            return ModelResponse(parts=[TextPart(" ".join(returned))])
        return ModelResponse(
            parts=[ToolCallPart("task", {"description": "check the claim", "subagent_type": to})]
        )

    return FunctionModel(respond)


def streaming_handing_on(to: str, *, ledger: SpendLedger) -> FunctionModel:
    """A `handing_on` that also narrates, for a tree observed through a surface.

    Same two requests booked to whichever delegation is running - a delegate's own
    two, then its own delegate's third - but with a `stream_function`, because a run
    with a sink is driven through `iter` and a `FunctionModel` with no stream raises
    there. Needed where the assertion is on the *panel* a surface shows, which only
    exists when the delegation is streamed.
    """
    args = {"description": "check the claim", "subagent_type": to}

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        ledger.book(ENTRY)
        returned = _tool_results(messages)
        if returned:
            return ModelResponse(parts=[TextPart(" ".join(returned))])
        return ModelResponse(parts=[ToolCallPart("task", args)])

    async def stream(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        ledger.book(ENTRY)
        returned = _tool_results(messages)
        if returned:
            yield " ".join(returned)
        else:
            yield {0: DeltaToolCall(name="task", json_args=json.dumps(args))}

    return FunctionModel(respond, stream_function=stream)


def asking(question: str, *, prefix: str = "answer: ") -> FunctionModel:
    """A delegate that asks the parent one question, then answers with what came back.

    Two requests, like `handing_on`: an `ask_parent` call first, then - once the
    person's answer is a tool result - the final text built from it. No
    `stream_function`, so nothing narrates and the library drives the delegate
    through `run`; a streamed half would be a branch these ask tests never reach.
    """

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        returned = _tool_results(messages)
        if returned:
            return ModelResponse(parts=[TextPart(f"{prefix}{' '.join(returned)}")])
        return ModelResponse(parts=[ToolCallPart("ask_parent", {"question": question})])

    return FunctionModel(respond)


def crashing(text: str) -> FunctionModel:
    """A model whose client raises, the way a provider failure arrives."""

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise RuntimeError(text)

    async def stream(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[DeltaToolCalls]:
        raise RuntimeError(text)
        yield {}  # pragma: no cover - makes this an async generator, like the client's

    return FunctionModel(respond, stream_function=stream)


def budget_stopped() -> FunctionModel:
    """A model whose next request the budget guard refuses, mid-delegation."""

    def ceiling() -> BudgetExceeded:
        return BudgetExceeded(
            limit_usd=Decimal("0.05"), spent_usd=Decimal("0.0500"), scope=BudgetScope.AGENT
        )

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise ceiling()

    async def stream(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[DeltaToolCalls]:
        raise ceiling()
        yield {}  # pragma: no cover - makes this an async generator, like the client's

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


def delegating_to(subagent: str) -> FunctionModel:
    """A model that delegates once and answers from what came back.

    For the delegate in the middle of a tree: the agent holding this model carries
    a delegation capability of its own, so its `task` call is a second level, which
    is the only way a nested delegation happens at all.
    """
    args = {"description": "find the price", "subagent_type": subagent}

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        returned = _tool_results(messages)
        if returned:
            return ModelResponse(parts=[TextPart(f"relayed: {returned[-1]}")])
        return ModelResponse(parts=[ToolCallPart("task", args, tool_call_id="the-middles-call")])

    async def stream(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        returned = _tool_results(messages)
        if returned:
            yield f"relayed: {returned[-1]}"
        else:
            yield {
                0: DeltaToolCall(
                    name="task", json_args=json.dumps(args), tool_call_id="the-middles-call"
                )
            }

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


def a_second_delegate() -> ResolvedSubagent:
    """Another delegate, for what only shows up beside a first one.

    One is enough for almost everything here; a *list* is what makes "this one runs
    differently" a statement about one line rather than about the agent.
    """
    return ResolvedSubagent(
        name="writer",
        description="Turns notes into prose.",
        build=delegate_agent(answering("written")),
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

    def __init__(self, *, yielding: bool = False) -> None:
        self.frames: list[SubagentEvent] = []
        # Whether writing a frame lets another coroutine run. The one sink that
        # matters writes to a WebSocket, so it does. Off by default because a sink
        # that yields makes every test in this file interleave differently for no
        # reason; on where the interleaving *is* the test - a drain that awaited
        # this and then acted on what it had read before, in
        # `test_two_delegations_settling_at_once_record_it_once`.
        self.yielding = yielding

    async def __call__(self, frame: SubagentEvent) -> None:
        self.frames.append(frame)
        if self.yielding:
            await asyncio.sleep(0)

    @property
    def kinds(self) -> list[str]:
        return [frame.kind for frame in self.frames]


def a_runtime(
    *delegates: ResolvedSubagent,
    ledger: SpendLedger | None = None,
    record: Callable[[DelegationOutcome], Awaitable[UUID | None]] | None = None,
    depth_remaining: int = 1,
    depth: int = 0,
) -> SubagentRuntime:
    return SubagentRuntime(
        subagents=delegates,
        record=record,
        depth_remaining=depth_remaining,
        depth=depth,
        ledger=ledger,
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


class Asker:
    """Stands in for the person waiting on the parent, reached through `ask_user`.

    The one-question shape `subagents_pydantic_ai`'s `ask_parent` calls
    `ctx.deps.ask_user` with - a question and options in, one answer string out.
    Records the questions so a test can assert the delegate reached a person rather
    than guessing.
    """

    def __init__(self, answer: str = "euros") -> None:
        self.answer = answer
        self.asked: list[str] = []

    async def __call__(self, question: str, _options: list[str]) -> str:
        self.asked.append(question)
        return self.answer


def a_context(
    sink: Sink | None = None,
    approvals: Approvals | None = None,
    *,
    run: str = "run-1",
    asker: Asker | None = None,
) -> RunContext[AgentDeps]:
    """A parent run, with an organization, a run id and collections of its own.

    All three matter to what a delegation inherits: the first two travel down to
    the delegate (the run id keys the workspace they share), and the collections
    deliberately do not.

    `run` is Pydantic AI's own run id, which is what the library scopes a task
    handle to - so a second value is how "another run's task" is spelt.

    `tool_call_id` is the model's id for the `task` call, which a real context
    always carries. It is what identifies a delegation across a park and a resume,
    so a context without one is a context in which a suspended delegate's place
    cannot be kept.
    """
    return RunContext(
        deps=AgentDeps(
            organization_id=uuid4(),
            run_id=uuid4(),
            kb_collection_names=["kb_only_the_parent_may_read"],
            subagent_events=sink,
            request_approval=approvals,
            ask_user=asker,
        ),
        model=TestModel(),
        usage=RunUsage(),
        run_id=run,
        tool_call_id="the-parents-task-call",
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

    async def test_a_delegating_agent_is_offered_no_way_to_answer_a_question(self):
        """The exact set a delegating agent's model reads, and why one is missing.

        `answer_subagent` answers a question a *background* delegate parked on, and
        no delegate here parks on one: a sync delegate that may ask (agenticos#184)
        is answered by a person through `ask_user`, never this tool, and an async
        delegate is not granted `can_ask_questions` at all. So the tool could only
        ever answer "that delegation is not waiting for an answer" - from a
        description in every turn's context, which is the strongest prompt surface in
        this product.

        It stays *declared*, which is the second assertion. A tool absent from
        `tools=` can be neither gated by the approval policy nor renamed by a
        binding, and that half of the same failure is silent. `UNREACHABLE_TOOLS`
        says what making it reachable would take, and why agenticos#184 was only
        half of that.

        `async`, so that this stays a statement about `answer_subagent` alone: it is
        the one tool withheld under *every* configuration, whereas the six
        background-lifecycle tools are withheld only from a `sync`-only agent - see
        `TestOfferedSet`. At the widest set, `answer_subagent` is the only thing
        missing.
        """
        capability = a_capability(a_runtime(a_delegate()), {"mode": "async"})
        toolset = capability.get_toolset()
        assert toolset is not None

        offered = frozenset(await toolset.get_tools(a_context()))

        assert offered == {
            "task",
            "check_task",
            "wait_tasks",
            "list_active_tasks",
            "send_message_to_subagent",
            "soft_cancel_task",
            "hard_cancel_task",
        }
        assert get("subagents").tool_ids >= UNREACHABLE_TOOLS

    async def test_allow_dynamic_in_the_config_alone_offers_no_extra_tool(self):
        """The setting has one reader, and it is not this capability.

        Acting on `allow_dynamic` means resolving the organization's model profiles
        and holding the run's budget guard, both of which are the runner's. So the
        runner reads the setting and the capability reads the *result*, on
        `SubagentRuntime.dynamic` - and a config saying yes with no resolved
        builder behind it offers nothing, rather than two tools whose factory does
        not exist. `tests/test_dynamic_specialists.py` has the other direction.

        `async`, so this stays a statement about `create_agent` and `delegate`
        being absent when nothing resolved them - not about the background-lifecycle
        set, which a `sync` agent would also be missing (`TestOfferedSet`).
        """
        capability = a_capability(a_runtime(a_delegate()), {"allow_dynamic": True, "mode": "async"})
        toolset = capability.get_toolset()
        assert toolset is not None

        offered = frozenset(await toolset.get_tools(a_context()))

        assert offered == get("subagents").tool_ids - {
            "create_agent",
            "delegate",
            *UNREACHABLE_TOOLS,
        }

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


class TestOfferedSet:
    """The six task-lifecycle tools, offered only when a background delegation is.

    Every one of `check_task`, `wait_tasks`, `list_active_tasks`,
    `send_message_to_subagent`, `soft_cancel_task` and `hard_cancel_task` takes or
    reports on a task id, and a `sync` delegation hands the model none: the library
    returns the answer and a `chat_trace_id` and nothing else. `sync` is the default
    mode, so an agent that can make no background delegation is the common case, not
    a corner - and six tool descriptions in every turn's context is the strongest
    prompt surface in the product spent describing actions that cannot happen.

    The predicate errs toward offering, because removing a tool an agent needs
    mid-turn is worse than offering one it will not use: `async`, `auto`, a delegate
    that prefers either, or permission to invent specialists each keep all six.
    """

    @staticmethod
    async def _offered(capability: Delegation) -> frozenset[str]:
        toolset = capability.get_toolset()
        assert toolset is not None
        return frozenset(await toolset.get_tools(a_context()))

    async def test_a_sync_only_agent_is_offered_task_and_nothing_else(self):
        """The whole of the fix: a `sync` agent with one delegate that overrides
        nothing still delegates, it just manages no tasks. So `task`, and none of
        the six - and none of `answer_subagent`, `create_agent` or `delegate`
        either, which is what leaves `task` alone."""
        offered = await self._offered(a_capability(a_runtime(a_delegate()), {"mode": "sync"}))

        assert offered == {"task"}
        assert not (offered & BACKGROUND_LIFECYCLE_TOOLS)

    async def test_async_mode_offers_every_lifecycle_tool(self):
        offered = await self._offered(a_capability(a_runtime(a_delegate()), {"mode": "async"}))

        assert offered >= BACKGROUND_LIFECYCLE_TOOLS

    async def test_auto_mode_offers_every_lifecycle_tool(self):
        """`auto` is resolved per delegation from what the model says about the
        task, so a delegation can go either way and the tools to collect a
        background one have to be there."""
        offered = await self._offered(a_capability(a_runtime(a_delegate()), {"mode": "auto"}))

        assert offered >= BACKGROUND_LIFECYCLE_TOOLS

    async def test_one_delegate_preferring_async_restores_them_for_a_sync_agent(self):
        """`_mode_for` resolves `delegate.preferred_mode or self.mode`, so a single
        delegate overriding a `sync` agent is enough to make a task id reachable -
        and the tools that take one have to come back with it."""
        capability = a_capability(
            a_runtime(a_delegate(preferred_mode="async"), a_second_delegate()), {"mode": "sync"}
        )

        assert await self._offered(capability) >= BACKGROUND_LIFECYCLE_TOOLS

    async def test_one_delegate_preferring_auto_restores_them_for_a_sync_agent(self):
        capability = a_capability(
            a_runtime(a_delegate(preferred_mode="auto"), a_second_delegate()), {"mode": "sync"}
        )

        assert await self._offered(capability) >= BACKGROUND_LIFECYCLE_TOOLS

    async def test_a_delegate_pinned_sync_does_not_restore_them(self):
        """A delegate that pins the mode the agent already has changes nothing: it
        cannot background, so the predicate must not read its override as one that
        could."""
        capability = a_capability(a_runtime(a_delegate(preferred_mode="sync")), {"mode": "sync"})

        assert not (await self._offered(capability) & BACKGROUND_LIFECYCLE_TOOLS)


class TestAskingTheParent:
    """A sync delegate may ask the person waiting on the parent, when its author allows.

    Off by default, gated on the mode, and never open to a specialist a model
    invented - the three things agenticos#184 turns on, without turning on more.
    `TestADynamicSpecialist` in `test_dynamic_specialists.py` holds the last of those.
    """

    async def test_a_sync_delegate_reaches_the_person_and_finishes_on_the_answer(self):
        """The whole feature, end to end and through the real library.

        The delegate asks, a person answers through the run's `ask_user` channel,
        and the delegation finishes using the answer - which the library injects
        `ask_parent` for a caller-supplied delegate to do only since
        subagents-pydantic-ai#76.
        """
        asker = Asker("euros")
        capability = a_capability(
            a_runtime(a_delegate(model=asking("which currency should I use?"))),
            {"allow_questions": True},
        )

        answer = await delegate_to(capability, a_context(asker=asker))

        assert asker.asked == ["which currency should I use?"]
        assert "euros" in answer

    def test_the_author_flag_and_the_mode_together_gate_asking(self):
        """`can_ask_questions` is granted only for a sync delegation whose author
        set `allow_questions` - the one combination with a person there to answer.

        A background delegation has handed back a task id with nobody waiting, and
        `auto` may become one, so neither is granted it however the flag is set. A
        delegate's own `preferred_mode` decides which it is, in both directions.
        """

        def may_ask(*, allow: bool, mode: DelegationMode, preferred: DelegationMode | None = None):
            journal = DelegationJournal(
                runtime=a_runtime(), mode=mode, allow_questions=allow, max_fanout=3, depth=0
            )
            return _config_for(a_delegate(preferred_mode=preferred), journal).get(
                "can_ask_questions"
            )

        assert may_ask(allow=True, mode="sync") is True
        assert may_ask(allow=False, mode="sync") is False
        assert may_ask(allow=True, mode="async") is False
        assert may_ask(allow=True, mode="auto") is False
        assert may_ask(allow=True, mode="async", preferred="sync") is True
        assert may_ask(allow=True, mode="sync", preferred="async") is False

    async def test_answer_subagent_stays_unoffered_even_when_questions_are_allowed(self):
        """The sync half never routes through `answer_subagent`: a person answers it.

        So opening questions must not start offering the tool - only the background
        half, which no delegate here reaches, ever would. See `UNREACHABLE_TOOLS`.
        """
        capability = a_capability(a_runtime(a_delegate()), {"allow_questions": True})
        toolset = capability.get_toolset()
        assert toolset is not None

        assert "answer_subagent" not in await toolset.get_tools(a_context())


class TestRecording:
    """What a delegation cost: its own share of the run's one shared ledger.

    Its own, and the emphasis is the whole of agenticos#180. The number used to be
    the ledger's *growth* across the delegation, which is the delegation's only
    while nothing else in the run spends inside the window - and a background
    delegation breaks that by definition. `TestBackgroundDelegations` and
    `TestADelegateThatDelegates` hold the two halves.
    """

    async def test_a_delegation_records_what_its_own_requests_cost(self):
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

    async def test_what_the_parent_spent_before_delegating_is_not_the_delegates(self):
        """The share, not the total: the parent has already spent before it delegates.

        A published delegate, so the number under test is the row it writes: the
        billed share reads the same as the delegate's own here, because it has no
        inline specialist below it (agenticos#228).
        """
        ledger = SpendLedger()
        ledger.book(ENTRY)
        recorder = Recorder()
        capability = a_capability(
            a_runtime(
                a_delegate(
                    model=answering(ledger=ledger), agent_id=uuid4(), agent_version_id=uuid4()
                ),
                ledger=ledger,
                record=recorder,
            )
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

    async def test_a_provider_failure_reaches_the_row_as_our_sentence_not_its_own(
        self, caplog: pytest.LogCaptureFixture
    ):
        """A delegated run's row refuses a provider's text, like its parent's (#699).

        What raises under a delegate is the same model client the parent runs on,
        and its message routinely carries the failing request URL with the key
        still in its query string. The parent's row already stores
        `run_failure_summary`'s sentence (#676); the child's row and its closing
        frame used to store the library's string with the provider's words
        embedded, on the same page.
        """
        vendor_text = "connect to https://llm.acme.internal/v1?api_key=sk-live-9f2c failed"
        recorder = Recorder()
        sink = Sink()
        capability = a_capability(
            a_runtime(a_delegate(model=crashing(vendor_text)), record=recorder)
        )

        with caplog.at_level(logging.WARNING), pytest.raises(Exception, match="researcher"):
            await delegate_to(capability, a_context(sink))

        (outcome,) = recorder.outcomes
        assert outcome.status == "failed"
        assert outcome.error is not None and "sk-live-9f2c" not in outcome.error
        assert outcome.error.startswith("The run did not finish (RuntimeError) - ")
        finished = sink.frames[-1]
        assert isinstance(finished, SubagentFinished)
        assert finished.error == outcome.error
        assert vendor_text in caplog.text

    async def test_a_delegate_stopped_by_the_budget_keeps_the_ceiling_sentence(self):
        """A budget breach is the second ceiling, and its numbers are the point.

        A delegate's requests are budget-checked inside the delegate's own run,
        so `BudgetExceeded` lands on the handle instead of propagating to the
        caller the parent's row is written by. Composed away like a provider
        crash, the row said "retry it" about a breached budget and dropped the
        ceiling's numbers.
        """
        recorder = Recorder()
        sink = Sink()
        capability = a_capability(a_runtime(a_delegate(model=budget_stopped()), record=recorder))

        with pytest.raises(Exception, match="researcher"):
            await delegate_to(capability, a_context(sink))

        (outcome,) = recorder.outcomes
        assert outcome.status == "failed"
        assert outcome.error is not None and "budget exhausted" in outcome.error
        assert "$0.05" in outcome.error
        assert "The run did not finish" not in outcome.error
        finished = sink.frames[-1]
        assert isinstance(finished, SubagentFinished)
        assert finished.error == outcome.error

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
        """A name no runtime resolved - an invented specialist, or one invented outright.

        The library refuses the unknown name a moment later, but the ceiling is
        asked for first, so it has to answer rather than raise.
        """
        assert _limits(a_runtime(a_delegate()), name="unresolved").request_limit == (
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

    def test_the_instructions_mark_the_delegate_that_does_not_follow_that_mode(self):
        """What the model reads has to be what happens.

        The ceiling note can only state one mode, and the mode is per *delegation*:
        an agent configured `sync` with one delegate pinned `async` told its model
        "each delegation blocks until the specialist answers" and then handed that
        delegate back a task id - so the model polled nothing, or waited for an
        answer that had already been given to it as an id. The configured mode is
        still stated, because it is what a specialist the model invents and a name
        it made up will run with.
        """
        capability = a_capability(
            a_runtime(a_delegate(preferred_mode="async"), a_second_delegate()), {"mode": "sync"}
        )

        instructions = capability.get_instructions()
        researcher, writer = (line for line in instructions.splitlines() if line.startswith("- **"))

        assert "runs in the background" in researcher
        assert "check_task" in researcher
        assert "(" not in writer
        assert "Each delegation blocks until the specialist answers." in instructions
        assert "A specialist marked otherwise above runs the way its own note says." in instructions

    def test_a_delegate_pinning_the_mode_it_would_have_had_is_not_marked(self):
        """A parenthesis repeating the sentence two lines below it is context paid
        for on every turn for no information."""
        capability = a_capability(
            a_runtime(a_delegate(preferred_mode="async"), a_second_delegate()), {"mode": "async"}
        )

        instructions = capability.get_instructions()

        assert "(" not in instructions.split("A specialist cannot see")[0]
        assert "marked otherwise" not in instructions

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
            a_runtime(
                a_delegate(
                    model=answering(ledger=ledger), agent_id=uuid4(), agent_version_id=uuid4()
                ),
                ledger=ledger,
                record=recorder,
            ),
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

    async def test_a_background_row_spans_the_delegate_not_the_settlement(self):
        """agenticos#191: the recorded span is the delegate's own, not the poll's.

        A background delegation is settled when it is next polled - here, the end
        of the run, after the parent has answered. Recorded off `now` that gave
        every background row a duration of zero, at the moment of settlement rather
        than the moment the delegate ran. The delegate pauses so its span is
        genuinely non-zero, and the assertion reads the recorded times against a
        clock read *before* the settlement - not a sleep measured after one.
        """
        recorder = Recorder()
        capability = a_capability(
            a_runtime(a_delegate(model=one_tool_call(), pause=0.02), record=recorder),
            {"mode": "async"},
        )
        ctx = a_context()

        started = await delegate_to(capability, ctx)
        assert "found it" in await call_tool(
            capability, ctx, "wait_tasks", {"task_ids": [task_id_in(started)]}
        )
        # The delegate has finished by now; the run that records it has not.
        before_settlement = datetime.now(UTC)
        assert await ends_the_run(capability, ctx) == "the parent answered"

        (outcome,) = recorder.outcomes
        assert outcome.started_at is not None and outcome.ended_at is not None
        # It ran for a real interval, not the instant `now` collapsed it to.
        assert outcome.ended_at > outcome.started_at
        # And it ran before the settlement, not at it: `now` at record time would
        # be inside `ends_the_run`, after this clock read.
        assert outcome.ended_at <= before_settlement

    async def test_what_the_parent_spends_after_it_finishes_is_not_the_delegates(self):
        """The defect agenticos#180 was filed for, with its own numbers.

        A background delegation is settled when it is next *polled* - the following
        `task` call, or `wrap_run`'s `finally` - which is arbitrarily later than the
        delegate finished. Measured as the growth of the shared total across that
        window, this delegation's $0.25 was reported as $0.75: the parent's ten
        requests, worth $0.50, landed on a delegate that had already answered. The
        error grows with however long the parent runs afterwards, and the number is
        what `agent_runs.cost_usd`, `SubagentFinished.cost_usd` and the delegation
        panel all carry.
        """
        ledger = SpendLedger()
        recorder = Recorder()
        capability = a_capability(
            a_runtime(
                a_delegate(
                    model=answering(ledger=ledger), agent_id=uuid4(), agent_version_id=uuid4()
                ),
                ledger=ledger,
                record=recorder,
            ),
            {"mode": "async"},
        )
        ctx = a_context()

        started = await delegate_to(capability, ctx)
        assert "found it" in await call_tool(
            capability, ctx, "wait_tasks", {"task_ids": [task_id_in(started)]}
        )
        # The parent carries on and answers, which is what puts the settlement at
        # the end of the run rather than anywhere near the delegate.
        for _ in range(10):
            ledger.book(PARENT_REQUEST)

        assert await ends_the_run(capability, ctx) == "the parent answered"

        (outcome,) = recorder.outcomes
        assert outcome.status == "completed"
        assert outcome.cost_usd == ENTRY.cost_usd
        assert (outcome.input_tokens, outcome.output_tokens) == (7, 3)
        # The parent's row is still the authority for the whole run, and it holds
        # every dollar: the share divides that total, it does not shrink it.
        assert ledger.total_usd == ENTRY.cost_usd + PARENT_REQUEST.cost_usd * 10

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

    async def test_two_delegations_settling_at_once_record_it_once(self):
        """The drain every delegation runs before its fan-out check, twice at once.

        Pydantic AI executes several tool calls from one model response
        concurrently, so a model that emits two `task` calls in one step runs two
        `_delegate` coroutines - and each drains the finished background
        delegations first. The entry used to be removed *after* the sink was
        awaited, and a sink that writes to a WebSocket yields, so both coroutines
        walked the same finished delegation: a second child `AgentRun` row for one
        delegation - double-billing that delegate's own monthly total - a second
        `subagent_complete` for a panel already closed, and a `KeyError` out of
        `call_tool` *before* `journal.begin`, where nothing settles the delegation
        and the run dies.

        Two delegations waiting to be settled rather than one, because that is what
        makes the drains genuinely overlap: claiming an entry is atomic - the
        snapshot and the `pop` have no `await` between them - so the second drain
        only ever finds an entry gone when the first one is *part way* through a
        list of several.
        """
        ledger = SpendLedger()
        recorder = Recorder()
        sink = Sink(yielding=True)
        capability = a_capability(
            a_runtime(a_delegate(model=answering(ledger=ledger)), ledger=ledger, record=recorder),
            {"mode": "async", "max_fanout": 4},
        )
        ctx = a_context(sink)
        started: list[str] = []

        async def delegate_once() -> None:
            started.append(task_id_in(await delegate_to(capability, ctx)))

        # Two `task` calls from one model response, which is how they overlap at
        # all - and then again once both have something to settle.
        async with anyio.create_task_group() as group:
            group.start_soon(delegate_once)
            group.start_soon(delegate_once)
        finished = list(started)
        await call_tool(capability, ctx, "wait_tasks", {"task_ids": finished})

        async with anyio.create_task_group() as group:
            group.start_soon(delegate_once)
            group.start_soon(delegate_once)

        closed = [frame.task_id for frame in sink.frames if frame.kind == "subagent_complete"]
        recorded = [outcome.task_id for outcome in recorder.outcomes]
        assert [recorded.count(task_id) for task_id in finished] == [1, 1]
        assert [closed.count(task_id) for task_id in finished] == [1, 1]
        assert capability.journal.in_flight() == 2

        await ends_the_run(capability, ctx)

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

    async def test_a_delegate_that_outlived_the_cancel_is_named_in_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ):
        """The guarantee above is bounded, and this capability used to claim it was not.

        `TaskManager.cancel_all` cancels every task and then waits at most
        `cancel_grace_seconds` before logging and moving on - deliberately, because
        an unbounded wait inside a `finally` hangs the application instead of one
        delegation. So "the run ended" does not mean "the delegate stopped": one
        whose cleanup outlasts the grace period is still executing after the row is
        written, writing into a workspace `finish` closed and appending to a ledger
        whose `cost_usd` was already persisted. Nothing here can stop it - the state
        is constructed rather than raced for, because what is under test is that it
        is *reported*, with the delegation named, rather than costing money from
        nowhere.
        """
        journal = _idle_journal(a_delegate())
        outlived = asyncio.create_task(asyncio.sleep(30))
        journal.tasks.handles["a1b2c3"] = TaskHandle(
            task_id="a1b2c3", subagent_name="researcher", description="find the price"
        )
        journal.tasks.tasks["a1b2c3"] = outlived

        with caplog.at_level(logging.WARNING):
            journal.cancel_in_flight()

        (logged,) = [
            record for record in caplog.records if record.message == "delegation_outlived_the_run"
        ]
        assert logged.task_ids == ["a1b2c3"]  # ty: ignore[unresolved-attribute] - from `extra`

        outlived.cancel()


class TestADelegateThatDelegates:
    """Three levels, and each one's spend recorded once.

    The second half of agenticos#180, and the quieter one. A mid-tree delegate's
    row and its own delegate's row both land in `monthly_spend(agent_id=...)`,
    which passes `include_delegations=True` - so a share that contained what the
    level below spent made "the researcher cost $X this month" the same money
    counted twice, on a number nobody can check against anything.
    """

    @staticmethod
    def _tree(ledger: SpendLedger, recorder: Recorder) -> tuple[Delegation, UUID, UUID]:
        """A parent, a researcher that delegates, and a fact-checker that answers.

        Assembled the way the runner assembles one: a runtime *per level*, each
        carrying the same ledger and the same recorder, and the delegation
        capability of one level bound to the agent of the level above it. `depth`
        is stamped by the runner rather than derived, which is why the inner
        runtime carries its own.
        """
        checker = ResolvedSubagent(
            name="fact-checker",
            description="Checks one claim.",
            build=delegate_agent(answering("checked", ledger=ledger)),
            agent_id=uuid4(),
            agent_version_id=uuid4(),
        )
        inner = a_capability(
            a_runtime(checker, ledger=ledger, record=recorder, depth_remaining=0, depth=1)
        )
        researcher = ResolvedSubagent(
            name="researcher",
            description="Researches a topic and cites its sources.",
            build=lambda: PydanticAgent(
                handing_on("fact-checker", ledger=ledger),
                output_type=[str, DeferredToolRequests],
                capabilities=[inner],
            ),
            agent_id=uuid4(),
            agent_version_id=uuid4(),
        )
        outer = a_capability(a_runtime(researcher, ledger=ledger, record=recorder))
        return outer, researcher.agent_id, checker.agent_id

    async def test_each_level_is_recorded_with_only_its_own_spend(self):
        """The grandchild's cost appears in exactly one row: the grandchild's.

        Three requests are made: two by the researcher - the one that delegates and
        the one that answers - and one by the fact-checker. Measured as a delta the
        researcher's window contained all three, so $0.75 was recorded against the
        researcher and $0.25 against the fact-checker: $1.00 of child rows for a run
        that cost $0.75.
        """
        ledger = SpendLedger()
        recorder = Recorder()
        capability, researcher, checker = self._tree(ledger, recorder)

        assert "checked" in await delegate_to(capability, a_context())

        by_agent = {outcome.agent_id: outcome for outcome in recorder.outcomes}
        assert by_agent[checker].cost_usd == ENTRY.cost_usd
        assert by_agent[researcher].cost_usd == ENTRY.cost_usd * 2
        # The whole run, once. The child rows divide the parent's total rather than
        # overlapping it, which is what `sum_cost_since(include_delegations=True)`
        # relies on to answer one agent's month.
        assert ledger.total_usd == ENTRY.cost_usd * 3
        assert sum(outcome.cost_usd for outcome in recorder.outcomes) == ledger.total_usd

    @staticmethod
    def _tree_with_inline_specialist(
        ledger: SpendLedger, recorder: Recorder
    ) -> tuple[Delegation, UUID]:
        """A published researcher that delegates to an *inline* fact-checker.

        The one shape agenticos#228 was filed for: the fact-checker has no
        `agent_id`, so it gets no run row of its own, and before the fix its spend
        was stamped to itself - a key nothing per-agent reads - and so was in no
        row at all. The researcher is published and streams (`streaming_handing_on`)
        so the panel a surface shows can be asserted beside the row a month sums.
        """
        checker = ResolvedSubagent(
            name="fact-checker",
            description="Checks one claim.",
            build=delegate_agent(answering("checked", ledger=ledger)),
        )
        inner = a_capability(
            a_runtime(checker, ledger=ledger, record=recorder, depth_remaining=0, depth=1)
        )
        researcher_id, researcher_version = uuid4(), uuid4()
        researcher = ResolvedSubagent(
            name="researcher",
            description="Researches a topic and cites its sources.",
            build=lambda: PydanticAgent(
                streaming_handing_on("fact-checker", ledger=ledger),
                output_type=[str, DeferredToolRequests],
                capabilities=[inner],
            ),
            agent_id=researcher_id,
            agent_version_id=researcher_version,
        )
        outer = a_capability(a_runtime(researcher, ledger=ledger, record=recorder))
        return outer, researcher_id

    async def test_a_published_delegates_row_takes_in_its_inline_specialists_spend(self):
        """The row is whole again and the panel is untouched - the shape of agenticos#228.

        Three requests at $0.25: two the researcher's, one the inline fact-checker's.
        Before the fix the researcher's row read $0.50 and the fact-checker's $0.25
        went to no month at all. Now the researcher's row is the full $0.75 while its
        fact-checker's *panel* still shows only its own $0.25 - what did this
        specialist cost, and what does this agent owe, kept apart.
        """
        ledger = SpendLedger()
        recorder = Recorder()
        sink = Sink()
        capability, researcher_id = self._tree_with_inline_specialist(ledger, recorder)

        assert "checked" in await delegate_to(capability, a_context(sink))

        outcomes = {outcome.subagent: outcome for outcome in recorder.outcomes}
        # The row: the published researcher's month is its own two requests plus the
        # one its inline specialist made - the whole run, not two-thirds of it.
        assert outcomes["researcher"].cost_usd == ENTRY.cost_usd * 3
        assert outcomes["researcher"].agent_id == researcher_id
        # The inline specialist bills nothing to a row of its own: it has none, and
        # its spend is already inside the researcher's. The runner drops this outcome
        # for want of an `agent_id`; the number it would carry is zero regardless.
        assert outcomes["fact-checker"].cost_usd == Decimal(0)
        assert outcomes["fact-checker"].agent_id is None

        # The panel: each still shows only what its own requests cost, so a surface
        # nests the fact-checker's $0.25 inside the researcher's own $0.50.
        finished = {
            frame.subagent: frame for frame in sink.frames if isinstance(frame, SubagentFinished)
        }
        assert finished["researcher"].cost_usd == ENTRY.cost_usd * 2
        assert finished["fact-checker"].cost_usd == ENTRY.cost_usd

        # The organization's bill is the whole ledger, once, and no dollar is under a
        # delegated row twice: the only row with a month here is the researcher's.
        assert ledger.total_usd == ENTRY.cost_usd * 3
        billed = sum(o.cost_usd for o in recorder.outcomes if o.agent_id is not None)
        assert billed == ledger.total_usd


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

    async def test_two_background_delegations_started_in_one_step_settle_separately(self):
        """Pydantic AI runs the tool calls in one model response concurrently, so
        two `task` calls overlap however the mode is configured - and the sweep that
        settles finished delegations mutates the same dict it is walking. Two
        distinct task ids, two outcomes, and a fan-out count back at zero is what
        says the bookkeeping is per delegation rather than per run."""
        ledger = SpendLedger()
        recorder = Recorder()
        capability = a_capability(
            a_runtime(a_delegate(model=answering(ledger=ledger)), ledger=ledger, record=recorder),
            {"mode": "async", "max_fanout": 2},
        )
        ctx = a_context()
        started: list[str] = []

        async def once() -> None:
            started.append(await delegate_to(capability, ctx))

        async with anyio.create_task_group() as group:
            group.start_soon(once)
            group.start_soon(once)

        task_ids = [task_id_in(answer) for answer in started]
        assert len(set(task_ids)) == 2
        await call_tool(capability, ctx, "wait_tasks", {"task_ids": task_ids})
        await ends_the_run(capability, ctx)

        assert [outcome.status for outcome in recorder.outcomes] == ["completed", "completed"]
        assert {outcome.task_id for outcome in recorder.outcomes} == set(task_ids)
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

        The resume path has to agree with that, and it does by having nothing to
        agree about: the suspension happens inside a task the delegating call
        returned from long ago, so it never propagates out of `call_tool` and no
        place is kept. A frame here would be an offer to continue a delegation whose
        caller has gone - a run parked on a `task` call that already answered.
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
        assert capability.journal.runtime.stash.parked == [], (
            "a background delegation must not offer a place to continue: its caller has gone"
        )

    async def test_a_sync_delegation_that_suspends_is_not_recorded_as_an_outcome(self):
        """The same status, the opposite meaning. Nothing went wrong and the answer
        is still coming: the signal parks the parent run, which is continued from
        the queue with this delegate carried on rather than started again - so a row
        written here would describe unfinished work, and then be written a second
        time when the continuation finishes it.

        Including at the end of the run, which is where the parked delegation meets
        the sweep that finishes everything still in flight as cancelled. `DEFERRED`
        is already terminal and `TaskHandle.finish` keeps the first terminal status,
        so the sweep passes over it - and it has to, or every approval a delegate
        parks on would be filed as a cancelled delegation the moment the parent run
        returned its deferred requests.
        """
        recorder = Recorder()

        def defer(_ctx: RunContext[AgentDeps]) -> str:
            raise ApprovalRequired

        capability = a_capability(
            a_runtime(a_delegate(model=one_tool_call(), on_call=defer), record=recorder)
        )
        ctx = a_context()

        with pytest.raises(ApprovalRequired):
            await delegate_to(capability, ctx)

        assert recorder.outcomes == []

        await ends_the_run(capability, ctx)

        assert recorder.outcomes == []
        assert [handle.status for handle in capability.journal.tasks.list_handles()] == [
            TaskStatus.DEFERRED
        ]

    async def test_a_parked_sync_delegate_closes_its_panel_and_frees_its_slot(self):
        """The two symptoms the missing frame left behind, on the same delegation.

        A sync delegate that stops for a person leaves the parent parked in the
        approval queue for as long as the approver takes. Refusing to record the
        outcome (the test above) refused to *narrate* it too, so two things broke
        that recording never should have (agenticos#173):

        *The panel never closed.* A surface that opened one on `subagent_start`
        read "the researcher is working" for the whole wait and forever if nobody
        decided. A `subagent_awaiting_approval` closes it with a state that means
        "waiting for a person" - the frame this asserts, naming the same delegation
        the opening one did so it is one panel and not two.

        *The slot never came back.* `close` filed the delegation into `_background`,
        where `settle_background` never settles a `DEFERRED` sync task, so
        `in_flight` stayed at 1 after the run had ended - the number the fan-out
        ceiling reads.

        Neither is an outcome: nothing is recorded here or when the run ends, and
        the awaiting frame is sent once rather than again by the end-of-run sweep.
        """
        recorder = Recorder()
        sink = Sink()

        def defer(_ctx: RunContext[AgentDeps]) -> str:
            raise ApprovalRequired

        capability = a_capability(
            a_runtime(a_delegate(model=one_tool_call(), on_call=defer), record=recorder)
        )
        ctx = a_context(sink)

        with pytest.raises(ApprovalRequired):
            await delegate_to(capability, ctx)

        assert sink.kinds[0] == "subagent_start"
        assert sink.kinds[-1] == "subagent_awaiting_approval"
        assert sink.frames[-1].task_id == sink.frames[0].task_id
        assert recorder.outcomes == [], "a parked delegation is not an outcome"
        assert capability.journal.in_flight() == 0

        await ends_the_run(capability, ctx)

        assert recorder.outcomes == [], "and still not one when the run ends"
        assert capability.journal.in_flight() == 0
        assert sink.kinds.count("subagent_awaiting_approval") == 1


class TestKeepingASuspendedDelegatesPlace:
    """What is stashed when a delegate stops for a person, and what is not.

    The continuation itself is `tests/test_subagent_nested_resume.py`, which asserts
    the property that matters: the same answer as an ungated run. Here is the half
    that has to be right before that is even possible - a suspended delegate's
    conversation kept where the resume will look for it, and nothing kept for a
    suspension no delegate produced.
    """

    async def test_a_suspended_delegate_leaves_its_conversation_and_its_identity(self):
        """The parent parks on `task`, so without this the delegate is simply gone.

        Everything a continuation needs, and all of it plain data: the delegate's
        messages, the `task` call that identifies the delegation on the replay, and
        which delegate it was. A live object here would be a service holding the
        request's session, kept past the turn that closes it.
        """
        agent_id, version_id = uuid4(), uuid4()
        capability = a_capability(
            a_runtime(
                a_delegate(
                    model=one_tool_call(),
                    gated=True,
                    agent_id=agent_id,
                    agent_version_id=version_id,
                )
            )
        )
        ctx = a_context(approvals=Approvals())

        with pytest.raises(ApprovalRequired):
            await delegate_to(capability, ctx)

        (parked,) = capability.journal.runtime.stash.parked
        assert parked.tool_call_id == ctx.tool_call_id
        assert (parked.subagent, parked.agent_id, parked.agent_version_id) == (
            "researcher",
            agent_id,
            version_id,
        )
        assert parked.parent_task_id is None
        assert parked.child_run_id is not None
        assert parked.messages, "an empty history is a delegate that has to start again"

    async def test_a_history_the_library_did_not_keep_still_leaves_a_frame(self):
        """A frame with no messages: a delegation that will be re-run, not lost.

        The library stores the history as best-effort telemetry - a serialisation
        failure there warns rather than failing the task - so a handle can record a
        suspension and carry no conversation. Written anyway, because the two
        outcomes are not "continue or re-run": they are "re-run" and "this run can
        never be continued at all". Pydantic AI refuses a resume that leaves a parked
        call without a result, and the parked call here is the parent's `task`.
        """
        journal = _idle_journal(a_delegate())
        # A handle recording the suspension and nothing else, which is what the
        # library leaves behind when capturing the history warned instead of
        # succeeding. Registered directly because there is no way to reach that
        # state through a delegation: the capture is inside the library.
        handle = TaskHandle(task_id="4f2a1b8c", subagent_name="researcher", description="find it")
        journal.tasks.handles[handle.task_id] = handle
        delegation = journal.begin(
            delegate=journal.runtime.named("researcher"),
            name="researcher",
            prompt="find the price",
            tool_args={},
            tool_call_id="the-parents-task-call",
        )
        delegation.task_id = handle.task_id

        journal.park(delegation)

        (parked,) = journal.runtime.stash.parked
        assert parked.tool_call_id == "the-parents-task-call"
        assert parked.messages == []

    async def test_a_suspension_from_a_delegation_that_never_started_keeps_nothing(self):
        """No task id means no delegate ran, so there is nothing that could have asked.

        The library assigns one before it runs anything. A suspension arriving here
        without one therefore came from something that is not a delegate, and a frame
        invented for it would claim the run's *own* parked calls as that delegate's -
        which is how one agent's replay would be handed another's tool call and
        refused.
        """
        journal = _idle_journal(a_delegate())
        toolset = DelegatingToolset(wrapped=_NeverStarts(), journal=journal)

        with pytest.raises(ApprovalRequired):
            await toolset.call_tool("task", {"subagent_type": "researcher"}, a_context(), None)

        assert journal.runtime.stash.parked == []
        assert journal.in_flight() == 0


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
        # A configured delegate is already keepable, so its opening frame carries no
        # definition to promote - `specialist` is the signal for a dynamic one alone.
        assert sink.frames[0].specialist is None

    async def test_a_nested_delegation_names_the_delegation_it_was_made_inside(self):
        """Depth says which level; only this says which panel.

        A surface with the depth alone has to guess the parent - "the most recent
        still-running delegation one level up" - and that is wrong whenever two
        delegations at that depth are running, which is the ordinary fan-out: the
        researcher's helper drawn inside the writer's panel, and the researcher
        showing no children. `SubagentRuntime.depth` is told rather than computed
        for exactly this reason, and the linkage was already read at `begin` for the
        parked tree; the frame simply carries it now.
        """
        sink = Sink()
        middle = ResolvedSubagent(
            name="editor",
            description="Puts the researcher's answer into shape.",
            build=lambda: PydanticAgent(
                delegating_to("researcher"),
                system_prompt="You coordinate.",
                output_type=[str, DeferredToolRequests],
                # Its own capability, its own runtime, one level in - the way the
                # runner builds a delegate that may delegate on.
                capabilities=[a_capability(a_runtime(a_delegate(), depth_remaining=0, depth=1))],
            ),
        )
        capability = a_capability(a_runtime(middle))

        await delegate_to(capability, a_context(sink), subagent_type="editor")

        opened = [frame for frame in sink.frames if frame.kind == "subagent_start"]
        outer, nested = opened
        assert (outer.subagent, outer.depth, outer.parent_task_id) == ("editor", 0, None)
        assert (nested.subagent, nested.depth) == ("researcher", 1)
        assert nested.parent_task_id == outer.task_id

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


class _NeverStarts:
    """A delegation tool that suspends before the library has started a task.

    Stands in for the wrapped toolset rather than for a delegate, because that is
    the only way to reach the case: the library assigns a task id before it runs
    anything, so nothing a real delegate does produces a suspension without one.
    """

    async def call_tool(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ApprovalRequired


def _idle_journal(*delegates: ResolvedSubagent) -> DelegationJournal:
    """A journal with no delegation in flight, for driving the stand-in directly.

    `_LazyAgent` asks it two things - is this delegation a background one, and is it
    one the run already parked on - and outside a `task` call the honest answer to
    both is no. Which is what the tests below are about: what the stand-in does when
    it is simply running a delegate.
    """
    journal = DelegationJournal(runtime=a_runtime(*delegates), mode="sync", max_fanout=3, depth=0)
    journal.tasks = TaskManager()
    return journal


class TestLazyDelegate:
    """The stand-in the library compiles in place of a delegate's agent."""

    async def test_both_entry_points_substitute_the_deps(self):
        """`iter` is the path the library takes with retries on - its default - and
        `run` the one it takes with them off. A substitution on only the path in
        use today is one that disappears the day a config changes."""
        seen: list[AgentDeps] = []
        delegate = a_delegate(model=one_tool_call(), collection_names=("kb_x",), seen=seen)
        proxy = _LazyAgent(delegate, _idle_journal(delegate))

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

        delegate = ResolvedSubagent(name="researcher", description="R", build=build_it)
        proxy = _LazyAgent(delegate, _idle_journal(delegate))
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
    """Only `task` is intercepted; what the other six do is `TestTaskLifecycle`."""

    async def test_they_pass_through_untouched(self):
        """Nothing here decides anything about them, and the accounting must not
        move either: a call that starts no delegation cannot open or close one.

        `async`, because these six are offered at all only when a background
        delegation is reachable - a `sync`-only agent is handed none of them,
        which is `TestOfferedSet`."""
        capability = a_capability(a_runtime(a_delegate()), {"mode": "async"})

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
