"""What delegation assumes about `subagents-pydantic-ai`, asserted.

Every one of these is a property of somebody else's library that our design rests
on. They are not tested anywhere else in this suite, and each of them fails
*silently* if the library changes shape: a renamed field is not a `TypeError` on
a dataclass whose fields we pass by keyword through an adapter, a
`clone_for_subagent` the library stops calling means a delegate quietly inherits
nothing, and a suspended child reported as completed means the parent reads
`DeferredToolRequests(...)` as a specialist's report and carries on.

So this file is the compat spike, kept. It is the test that goes red when
`uv sync` moves the floor, and it names in each docstring what the failure would
look like in production if it were not here - which is the only reason a contract
test earns its place beside the behaviour tests.

Pinned floor: 0.2.16, for three fixes filed from this integration. Two of them
are asserted below
(`test_a_suspended_child_parks_the_parent_and_is_never_reported_as_completed`,
`test_a_handler_factory_receives_the_task_id_of_its_delegation`); the third,
`cancel_all`'s bounded wait, is asserted through `AgentSession` where our
cancellation actually comes from, not here.

Two of these tests exist because writing them found something the plan for #40
had wrong, and both change what the implementation has to do:

- streaming a delegation makes every child request a **streamed** request, so a
  delegate whose provider cannot stream works from the API and breaks in chat;
- a gated tool inside a delegate parks the parent on the **`task`** call, while the
  approval row - written by the child's own gate - names the child's tool. The
  queue is therefore right and *resume* is wrong: the granted approval is keyed on
  an id the replayed parent never asks about.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai.usage import UsageLimits
from subagents_pydantic_ai import (
    SubAgentCapability,
    SubAgentConfig,
    SubAgentDepsProtocol,
)

from app.agents.deps import AgentDeps

pytestmark = pytest.mark.anyio

DELEGATE = "researcher"


@dataclass
class _Seen:
    """What the library handed our code, recorded for assertions."""

    child_deps: list[AgentDeps] = field(default_factory=list)
    limit_calls: list[tuple[str, int | None]] = field(default_factory=list)
    handler_task_ids: list[str] = field(default_factory=list)
    child_event_names: list[str] = field(default_factory=list)


def _delegating_parent(prompt: str = "research pydantic") -> FunctionModel:
    """A parent that delegates once, then answers.

    A `FunctionModel` rather than a mocked toolset: the point of these tests is
    that the library's *tools* behave as documented when a model calls them, and
    a mock would assert our own stub instead.
    """

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if not any(
            isinstance(part, ToolCallPart) for message in messages for part in message.parts
        ):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="task",
                        args={"description": prompt, "subagent_type": DELEGATE},
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("delegated and done")])

    return FunctionModel(respond)


def _answering_child(answer: str = "found three papers") -> FunctionModel:
    """A delegate that answers in text, and can do it streamed.

    `stream_function` is not optional decoration here - see
    `test_streaming_a_delegation_makes_every_child_request_a_streamed_one`. A
    child model without one raises the moment a handler is attached.
    """

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(answer)])

    async def respond_streamed(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str]:
        for word in answer.split():
            yield f"{word} "

    return FunctionModel(respond, stream_function=respond_streamed)


def _child_agent(model: FunctionModel, seen: _Seen) -> PydanticAgent[AgentDeps, Any]:
    """A delegate built the way our factory builds one, minus the platform.

    `output_type=[str, DeferredToolRequests]` is the part that matters and the
    part `build_agent` always sets: it is why a parked child ends its run with an
    output object instead of raising, which is the whole subject of the last test.
    """
    child = PydanticAgent[AgentDeps, Any](
        model=model,
        system_prompt="You research things.",
        output_type=[str, DeferredToolRequests],
    )

    @child.tool
    def note_deps(ctx: RunContext[AgentDeps]) -> str:
        """Record the deps this delegation was given."""
        seen.child_deps.append(ctx.deps)
        return "noted"

    return child


def _parent_agent(
    child: PydanticAgent[AgentDeps, Any],
    seen: _Seen,
    *,
    max_nesting_depth: int = 1,
    child_max_steps: int | None = 7,
    with_handler: bool = True,
) -> PydanticAgent[AgentDeps, Any]:
    def limits_for(_ctx: RunContext[AgentDeps], config: SubAgentConfig) -> UsageLimits | None:
        seen.limit_calls.append((config["name"], child_max_steps))
        return None if child_max_steps is None else UsageLimits(request_limit=child_max_steps)

    def handler_for(
        _ctx: RunContext[AgentDeps], _config: SubAgentConfig, task_id: str
    ) -> Any:  # the library types this as an EventStreamHandler
        seen.handler_task_ids.append(task_id)

        async def handle(_run_ctx: RunContext[Any], events: Any) -> None:
            async for event in events:
                seen.child_event_names.append(type(event).__name__)

        return handle

    capability = SubAgentCapability(
        subagents=[
            SubAgentConfig(
                name=DELEGATE,
                description="Researches a topic and cites sources",
                instructions="You research things.",
                agent=child,
            )
        ],
        include_general_purpose=False,
        max_nesting_depth=max_nesting_depth,
        usage_limits=limits_for,
        event_stream_handler_factory=handler_for if with_handler else None,
    )
    return PydanticAgent[AgentDeps, Any](
        model=_delegating_parent(),
        output_type=[str, DeferredToolRequests],
        capabilities=[capability],
    )


async def test_agent_deps_satisfies_the_protocol_the_library_calls() -> None:
    """`AgentDeps` is what every delegation is handed.

    A `runtime_checkable` Protocol, so this is a real check rather than a type
    comment: if `clone_for_subagent` is dropped or renamed, the library's own
    call site raises `AttributeError` on the first `task` call - in production,
    on a published agent nobody had touched.
    """
    assert isinstance(AgentDeps(), SubAgentDepsProtocol)


async def test_a_delegation_runs_the_agent_we_supplied() -> None:
    """A pre-built `agent` on the config is used instead of one the library makes.

    This is what design B rests on. If the library ever constructed its own agent
    from the config's `model` and `instructions` instead, a delegate would run
    without our budget guard, without our approval gate and without its own
    capabilities - and it would still answer, so nothing would look broken.
    """
    seen = _Seen()
    child = _child_agent(_answering_child(), seen)
    parent = _parent_agent(child, seen)

    result = await parent.run("research pydantic", deps=AgentDeps())

    assert result.output == "delegated and done"
    # The child's own tool never ran, so prove the delegation happened through
    # the transcript rather than through a side effect that may not occur.
    delegated = [
        part
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolCallPart) and part.tool_name == "task"
    ]
    assert len(delegated) == 1


async def test_a_delegate_is_handed_deps_cloned_from_its_parent() -> None:
    """The child's deps come from `clone_for_subagent`, not from the parent object.

    Asserted on identity as well as content: the library documents that each
    delegation gets its *own* instance, and a shared one would let two concurrent
    specialists write into each other's state.

    The second assertion is the one that pins a defect. The clone **replaces** the
    deps our factory built for the child, so anything resolved per-delegate and
    left only on those deps is silently discarded - which is what happened to
    `kb_collection_names`: a delegate configured with a collection resolved it,
    was handed deps without it, and answered "No active knowledge bases selected"
    to every search while looking correctly configured (issue #166). The parent's
    collections are deliberately *not* inherited either, so the delegation
    capability is what puts the delegate's own back, from
    `ResolvedSubagent.collection_names`.
    """
    seen = _Seen()

    def calls_its_tool(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if not seen.child_deps:
            return ModelResponse(parts=[ToolCallPart(tool_name="note_deps", args={})])
        return ModelResponse(parts=[TextPart("noted and done")])

    child = _child_agent(FunctionModel(calls_its_tool), seen)
    parent_deps = AgentDeps(user_name="Kacper", kb_collection_names=["parent_docs"])
    # Without a handler, so the child's tool call goes through the non-streaming
    # path this `FunctionModel` supports. What is under test here is the clone,
    # not the transport.
    parent = _parent_agent(child, seen, max_nesting_depth=2, with_handler=False)

    await parent.run("research pydantic", deps=parent_deps)

    assert len(seen.child_deps) == 1
    child_deps = seen.child_deps[0]
    assert child_deps is not parent_deps
    assert child_deps.user_name == "Kacper"
    assert child_deps.kb_collection_names == []


async def test_a_per_delegation_usage_limit_is_resolved_from_the_config() -> None:
    """The `usage_limits` factory is called per delegation, with that delegate's config.

    It is the only thing between a delegation and a loop that delegates to a
    loop, and it is resolved from the config rather than set once because each
    delegate carries its own `max_steps`.
    """
    seen = _Seen()
    parent = _parent_agent(_child_agent(_answering_child(), seen), seen, child_max_steps=7)

    await parent.run("research pydantic", deps=AgentDeps())

    assert seen.limit_calls == [(DELEGATE, 7)]


async def test_a_handler_factory_receives_the_task_id_of_its_delegation() -> None:
    """Streaming is labelled per delegation, which is what makes a fan-out readable.

    The reason `event_stream_handler_factory` was worth asking upstream for: with
    only a handler on the agent, three concurrent specialists' text deltas arrive
    with nothing to tell them apart, and a surface can either interleave them into
    one unreadable paragraph or drop two of the three.
    """
    seen = _Seen()
    parent = _parent_agent(_child_agent(_answering_child(), seen), seen)

    await parent.run("research pydantic", deps=AgentDeps())

    assert len(seen.handler_task_ids) == 1
    assert seen.handler_task_ids[0]
    # The child's own model response reached the handler, so the events a chat
    # surface renders are actually available to us.
    assert seen.child_event_names


async def test_a_suspended_child_parks_the_parent_and_is_never_reported_as_completed() -> None:
    """A gated tool inside a delegate parks the whole run, naming the wrong tool.

    Two findings in one test, and the second was not what the plan predicted.

    **It does not lie.** The defect filed as
    `vstorm-co/subagents-pydantic-ai#64` and fixed in 0.2.15 was that a child
    whose `output_type` includes `DeferredToolRequests` never raises - it ends its
    run with an output object - and the library used to serialise that object and
    hand the parent `{"calls": [], "approvals": [...]}` as the specialist's
    report, with the task marked completed. Every agent `build_agent` makes
    declares that output type, so this was our default path rather than an edge
    case. It is fixed: the parent's run ends parked, and no completed task report
    is produced.

    **But the parent parks on its own `task` call.** The run's
    `DeferredToolRequests.approvals` holds the parent's *delegation* call - the one
    whose arguments are `{"description": ..., "subagent_type": "researcher"}` - and
    not the child's `send_email`.

    That is not a problem for the approval *queue*, and an earlier version of this
    docstring said it was. The row is written by the child's own `ApprovalGate`,
    which builds `ApprovalRequest(tool_name=tool_def.name, ...)` from the call it
    intercepted, so a reviewer is shown `send_email` and its arguments. The queue
    is honest.

    It is a problem for **resume**, and a sharper one:

    - `ApprovalChannel` records `parked[approval_id] = request.tool_call_id`, which
      is the *child's* tool call id;
    - `_decisions` therefore builds `deferred.approvals[child_tool_call_id]`;
    - but replaying the parent presents its own parked call, whose id belongs to
      `task`.

    So the granted approval maps to an id the replayed run never asks about, the
    delegation starts again from nothing, and **what the reviewer approved is not
    what executes** - the second time round the model may not even call the same
    tool. Silent, and a correctness hole rather than a rough edge. The parent's
    history also holds no record of the child's conversation, so there is nothing
    to continue from even if the ids lined up.

    Closing it means intercepting the child's parked state where the delegation is
    made - `DelegatingToolset.call_tool` in our capability package - stashing the
    child's messages and its parked ids, and resuming that child rather than
    re-running the parent's tool call.
    """
    seen = _Seen()

    child = PydanticAgent[AgentDeps, Any](
        model=FunctionModel(
            lambda _messages, _info: ModelResponse(
                parts=[ToolCallPart(tool_name="send_email", args={"to": "board@example.com"})]
            )
        ),
        output_type=[str, DeferredToolRequests],
    )

    @child.tool
    def send_email(_ctx: RunContext[AgentDeps], to: str) -> str:
        """A side-effecting tool that a person has to approve."""
        raise ApprovalRequired

    parent = _parent_agent(child, seen, with_handler=False)
    result = await parent.run("research pydantic", deps=AgentDeps())

    # The parent parked rather than being handed a report. Nothing was returned to
    # its model at all, which is what "does not lie" means concretely.
    assert isinstance(result.output, DeferredToolRequests)
    reports = [
        part
        for message in result.all_messages()
        for part in message.parts
        if getattr(part, "tool_name", None) == "task" and hasattr(part, "content")
    ]
    assert not reports, f"a parked delegation produced a tool result: {reports!r}"

    # ...and the approval names the delegation, not the child's tool. Pinned so
    # that a library version which starts surfacing the child's call turns this
    # red and the wrapper can be simplified rather than kept out of habit.
    parked = result.output.approvals
    assert [call.tool_name for call in parked] == ["task"]
    assert parked[0].args_as_dict(raise_if_invalid=False).get("subagent_type") == DELEGATE
    assert "send_email" not in str(parked[0].args)


async def test_streaming_a_delegation_makes_every_child_request_a_streamed_one() -> None:
    """Attaching a handler changes the transport, not just the observability.

    Found writing these tests, and it is the kind of thing that would otherwise
    be found by a customer. Setting `event_stream_handler_factory` makes the
    library drive each child through `agent.iter()` and open a **streamed**
    request - so a delegate whose model or provider cannot stream stops working
    the moment somebody opens the chat surface, while the same agent run from the
    API or a schedule is fine.

    Two consequences we act on rather than discover later: the event sink is set
    only by surfaces that can show a delegation, so a channel or an API run
    attaches no handler and takes the plain path; and the capability must not
    attach a handler when the sink is `None`, which would impose streaming on
    every surface for the benefit of none.

    Asserted through the failure itself, because a `FunctionModel` with no
    `stream_function` is exactly the shape of a model that cannot stream.
    """
    seen = _Seen()
    cannot_stream = FunctionModel(
        lambda _messages, _info: ModelResponse(parts=[TextPart("answered")])
    )
    child = _child_agent(cannot_stream, seen)
    parent = _parent_agent(child, seen, with_handler=True)

    result = await parent.run("research pydantic", deps=AgentDeps())

    reports = [
        str(part.content)
        for message in result.all_messages()
        for part in message.parts
        if getattr(part, "tool_name", None) == "task" and hasattr(part, "content")
    ]
    assert reports, "the delegation produced no tool result at all"
    assert "stream_function" in reports[0], (
        "a non-streaming child no longer fails under a handler - if the library "
        "now falls back to a plain request, the capability may attach a handler "
        f"unconditionally and this test should say so instead. Got: {reports[0]!r}"
    )


async def test_the_capability_fields_our_adapter_passes_still_exist() -> None:
    """A rename in the library is a silent behaviour change here, so name them.

    Our adapter passes these by keyword. A dataclass that no longer declares one
    raises, which is fine - but one that *renames* it while keeping a default
    leaves us building a delegation with the library's default instead of the
    author's configuration, and an agent whose fan-out ceiling silently became
    the library's is not something a behaviour test would notice.
    """
    declared = set(SubAgentCapability.__dataclass_fields__)
    assert {
        "subagents",
        "include_general_purpose",
        "max_nesting_depth",
        "usage_limits",
        "event_stream_handler",
        "event_stream_handler_factory",
        "max_result_chars",
        "cancel_grace_seconds",
        "delegation_configuration",
        "allowed_models",
        "capabilities_map",
        "default_agent_factory",
        "toolsets_factory",
    } <= declared
