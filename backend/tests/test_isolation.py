"""Tests for isolated runs - what an eval may execute, and what it only records.

The guarantee worth proving is the refusal: a tool that writes and has no test
connection never executes, and what it was asked to do is kept. Most tests drive
a real Pydantic AI agent, because "blocked" means the tool function was never
entered - a mock of the handler cannot say that.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from app.agents.capabilities import REGISTRY, load_builtins
from app.agents.capabilities import get as get_capability
from app.agents.capabilities.approval import ApprovalGate
from app.agents.deps import AgentDeps
from app.agents.factory import build_agent
from app.agents.isolation import (
    MAX_RECORDED_ARGS_CHARS,
    CallRow,
    IsolationGuard,
    RecordedCall,
    RunIsolation,
    ToolClass,
    ToolRecording,
    capability_tools,
    classify,
    normalized_args,
    recorded_args,
    recorded_calls,
)
from app.agents.mcp import MCP_ORIGIN
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.secret_kinds import ApiKeySecret
from app.db.models.intercepted_tool_call import InterceptionOutcome, InterceptionReason

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


class _World:
    """What actually happened outside the run."""

    def __init__(self) -> None:
        self.effects: list[tuple[str, str]] = []

    def toolset(
        self, tool: str, *, test: bool, read_only: bool, trusted: bool = True
    ) -> AbstractToolset[Any]:
        """One MCP-shaped tool: stamped with its origin, annotated by its server.

        `trusted` is whether its connection believes the server's annotations.
        """
        toolset: FunctionToolset[Any] = FunctionToolset()
        effects = self.effects

        def act(name: str) -> str:
            effects.append((tool, name))
            return f"{tool} did {name}"

        toolset.add_function(act, name=tool)
        return toolset.with_metadata(
            **{
                MCP_ORIGIN: {"test": test, "trust_read_only_hints": trusted},
                "annotations": {"readOnlyHint": read_only},
            }
        )


def _calls_then_answers(*calls: tuple[str, dict[str, Any]]) -> FunctionModel:
    """A model that asks for every call at once, then answers with what it saw."""

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name=name, args=args, tool_call_id=f"call-{n}")
                    for n, (name, args) in enumerate(calls)
                ]
            )
        returned = [
            str(part.content) for part in messages[-1].parts if isinstance(part, ToolReturnPart)
        ]
        return ModelResponse(parts=[TextPart(" | ".join(returned))])

    return FunctionModel(respond)


async def _run(
    isolation: RunIsolation, toolsets: list[AbstractToolset[Any]], model: FunctionModel
) -> str:
    agent = Agent(
        model,
        deps_type=AgentDeps,
        capabilities=[IsolationGuard(isolation=isolation)],
        toolsets=toolsets,
    )
    result = await agent.run("go", deps=AgentDeps())
    return result.output


class TestTheArgumentsAHeldCallKeeps:
    async def test_they_are_what_the_model_sent_and_fit_a_json_column(self):
        """Validated arguments hold a `date` here, which the JSONB write cannot
        serialize - and losing that write loses the eval's whole trajectory."""
        isolation = RunIsolation()
        toolset: FunctionToolset[Any] = FunctionToolset()

        def schedule(on: datetime.date, note: str = "") -> str:
            raise AssertionError("a held call must not run")

        toolset.add_function(schedule)

        await _run(isolation, [toolset], _calls_then_answers(("schedule", {"on": "2026-10-14"})))

        (held,) = isolation.intercepted
        assert held.args == {"on": "2026-10-14"}
        assert json.loads(json.dumps(held.args)) == held.args

    def test_an_outsized_argument_list_is_kept_as_its_size(self):
        call = ToolCallPart(
            tool_name="send",
            args={"body": "x" * MAX_RECORDED_ARGS_CHARS},
            tool_call_id="c",
        )

        assert recorded_args(call) == {"truncated": True, "chars": MAX_RECORDED_ARGS_CHARS + 12}


class TestWhatAnIsolatedRunExecutes:
    async def test_a_write_without_a_test_connection_never_runs_and_is_recorded(self):
        """The acceptance criterion: the tool function is never entered, and the
        intended call is kept with its arguments for trajectory scoring."""
        world = _World()
        isolation = RunIsolation()

        answer = await _run(
            isolation,
            [world.toolset("crm_create", test=False, read_only=False)],
            _calls_then_answers(("crm_create", {"name": "Ada"})),
        )

        assert world.effects == []
        assert [
            (call.tool_call_id, call.tool_name, call.tool_id, call.args, call.outcome)
            for call in isolation.intercepted
        ] == [
            (
                "call-0",
                "crm_create",
                "tool:crm_create",
                {"name": "Ada"},
                InterceptionOutcome.BLOCKED,
            )
        ]
        # The model is told, so it does not report a contact it never created.
        assert "Not executed" in answer

    async def test_a_test_connection_and_a_read_run_where_a_production_write_cannot(self):
        world = _World()
        isolation = RunIsolation()

        await _run(
            isolation,
            [
                world.toolset("crm_find", test=False, read_only=True),
                world.toolset("sandbox_create", test=True, read_only=False),
                world.toolset("crm_create", test=False, read_only=False),
            ],
            _calls_then_answers(
                ("crm_find", {"name": "Ada"}),
                ("sandbox_create", {"name": "Ada"}),
                ("crm_create", {"name": "Ada"}),
            ),
        )

        assert world.effects == [("crm_find", "Ada"), ("sandbox_create", "Ada")]
        assert [call.tool_name for call in isolation.intercepted] == ["crm_create"]

    async def test_a_production_tool_claiming_to_read_is_held_unless_its_connection_trusts_it(
        self,
    ):
        """`readOnlyHint` is the server's word: a write mislabelled as a read must
        not reach production because the server said so."""
        world = _World()
        isolation = RunIsolation()

        await _run(
            isolation,
            [
                world.toolset("crm_purge", test=False, read_only=True, trusted=False),
                world.toolset("docs_find", test=False, read_only=True, trusted=True),
            ],
            _calls_then_answers(("crm_purge", {"name": "Ada"}), ("docs_find", {"name": "Ada"})),
        )

        assert world.effects == [("docs_find", "Ada")]
        assert [(call.tool_name, call.outcome, call.reason) for call in isolation.intercepted] == [
            ("crm_purge", InterceptionOutcome.BLOCKED, InterceptionReason.WRITES)
        ]

    async def test_a_recording_answers_the_same_call_without_executing_it(self):
        world = _World()
        isolation = RunIsolation(
            recording=ToolRecording(
                [
                    RecordedCall(
                        tool_id="tool:crm_find",
                        args=normalized_args({"name": "Ada"}),
                        result="Ada, customer since 2019",
                    )
                ]
            )
        )

        answer = await _run(
            isolation,
            [world.toolset("crm_find", test=False, read_only=True)],
            _calls_then_answers(("crm_find", {"name": "Ada"})),
        )

        assert world.effects == []
        assert answer == "Ada, customer since 2019"
        assert [call.outcome for call in isolation.intercepted] == [InterceptionOutcome.REPLAYED]

    async def test_a_recording_matches_what_the_model_sent_not_the_filled_in_defaults(self):
        world_calls: list[int] = []
        toolset: FunctionToolset[Any] = FunctionToolset()

        def crm_find(name: str, limit: int = 10) -> str:
            world_calls.append(limit)
            return "live"

        toolset.add_function(crm_find)
        isolation = RunIsolation(
            recording=ToolRecording(
                [RecordedCall("tool:crm_find", normalized_args({"name": "Ada"}), "recorded")]
            )
        )

        answer = await _run(
            isolation,
            [toolset.with_metadata(**{MCP_ORIGIN: {"test": False}})],
            _calls_then_answers(("crm_find", {"name": "Ada"})),
        )

        assert (answer, world_calls) == ("recorded", [])

    @pytest.mark.parametrize("live_reads", [False, True])
    async def test_a_call_the_recording_does_not_hold_is_divergent(self, live_reads):
        """Another call's result would fabricate the difference being measured.
        A read may run live where the run allows it; a write never does - not
        even to a test connection, because the comparison is with what happened."""
        world = _World()
        isolation = RunIsolation(recording=ToolRecording([]), live_reads=live_reads)

        await _run(
            isolation,
            [
                world.toolset("crm_find", test=False, read_only=True),
                world.toolset("sandbox_create", test=True, read_only=False),
            ],
            _calls_then_answers(
                ("crm_find", {"name": "Grace"}), ("sandbox_create", {"name": "Grace"})
            ),
        )

        assert world.effects == ([("crm_find", "Grace")] if live_reads else [])
        assert [(call.tool_name, call.outcome) for call in isolation.intercepted] == [
            *([] if live_reads else [("crm_find", InterceptionOutcome.DIVERGENT)]),
            ("sandbox_create", InterceptionOutcome.DIVERGENT),
        ]

    async def test_a_delegates_calls_are_attributed_to_it(self):
        delegate_id = uuid.uuid4()
        isolation = RunIsolation()
        guard = IsolationGuard(isolation=isolation, agent_id=delegate_id)

        await guard.wrap_tool_execute(
            AsyncMock(),
            call=ToolCallPart(tool_name="send", args={}, tool_call_id="c"),
            tool_def=ToolDefinition(name="send"),
            args={"to": "a@example.com"},
            handler=AsyncMock(),
        )

        assert isolation.intercepted[0].agent_id == delegate_id


class TestClassification:
    def test_an_mcp_tool_reads_only_when_its_server_says_so_and_is_believed(self):
        def tool(*, hint: bool | None, trusted: bool) -> ToolDefinition:
            return ToolDefinition(
                name="crm_find",
                metadata={
                    MCP_ORIGIN: {"test": False, "trust_read_only_hints": trusted},
                    "annotations": None if hint is None else {"readOnlyHint": hint},
                },
            )

        assert classify(tool(hint=True, trusted=True), {}).read_only is True
        assert classify(tool(hint=True, trusted=False), {}).read_only is False
        assert classify(tool(hint=None, trusted=True), {}).read_only is False

    def test_a_stamp_from_before_trust_existed_believes_no_hint(self):
        stamped = ToolDefinition(
            name="crm_find",
            metadata={MCP_ORIGIN: {"test": False}, "annotations": {"readOnlyHint": True}},
        )

        assert classify(stamped, {}) == ToolClass("tool:crm_find", read_only=False)

    def test_an_mcp_tool_is_never_mistaken_for_a_registry_tool_of_the_same_name(self):
        """The stamp decides, not the name: a server cannot borrow a read's identity."""
        tool = ToolDefinition(name="search_documents", metadata={MCP_ORIGIN: {"test": False}})
        table = {"search_documents": ToolClass("capability:knowledge.search_documents", True)}

        assert classify(tool, table).read_only is False

    def test_a_registry_tool_is_what_its_declaration_says(self):
        table = {"search_documents": ToolClass("capability:knowledge.search_documents", True)}

        assert classify(ToolDefinition(name="search_documents"), table) == table["search_documents"]

    def test_a_tool_nothing_declared_writes(self):
        assert classify(ToolDefinition(name="connect_account"), {}).read_only is False

    def test_the_frameworks_own_reads_run(self):
        assert classify(ToolDefinition(name="load_capability"), {}).read_only is True
        assert classify(ToolDefinition(name="search_tools"), {}).read_only is True

    def test_registry_tools_are_keyed_by_the_name_the_model_calls(self):
        """A rename keeps the stable id, so a recording still matches it."""
        spec = AgentSpec(
            name="Notes",
            capabilities=[
                {
                    "id": "memory_files",
                    "tool_overrides": {"read_memory": {"name": "look_up_note"}},
                },
                {"id": "clock", "enabled": False},
            ],
        )

        tools = capability_tools(spec)

        assert tools["look_up_note"] == ToolClass("capability:memory_files.read_memory", True)
        assert tools["write_memory"].read_only is False

    def test_a_swapped_key_reaches_a_test_system_only_where_the_capability_says_so(
        self, monkeypatch
    ):
        """A key can stand in for a credential while a URL in the config still
        points the writes at production, so the swap alone proves nothing."""
        spec = AgentSpec(
            name="Memory",
            capabilities=[{"id": "memory_mem0", "config": {}, "secret_id": uuid.uuid4()}],
        )
        swapped = frozenset({"memory_mem0"})

        assert not capability_tools(spec, test_bindings=swapped)["remember"].test

        monkeypatch.setitem(
            REGISTRY,
            "memory_mem0",
            dataclasses.replace(get_capability("memory_mem0"), test_key_isolates=True),
        )

        assert capability_tools(spec, test_bindings=swapped)["remember"].test
        assert not capability_tools(spec, test_bindings=frozenset())["remember"].test


class TestRecordings:
    def test_rows_become_recorded_calls_under_the_original_versions_ids(self):
        """`look_up_note` was the original version's rename of `read_memory`."""
        calls = recorded_calls(
            [
                CallRow("look_up_note", {"b": 2, "a": 1}, '{"note": "x"}'),
                CallRow("crm_find", {"name": "Ada"}, "Ada"),
            ],
            tools={"look_up_note": ToolClass("capability:memory_files.read_memory", True)},
        )

        assert calls == [
            RecordedCall("capability:memory_files.read_memory", '{"a":1,"b":2}', '{"note": "x"}'),
            RecordedCall("tool:crm_find", '{"name":"Ada"}', "Ada"),
        ]

    def test_identical_calls_are_answered_in_order_and_then_not_at_all(self):
        recording = ToolRecording(
            [RecordedCall("tool:now", "{}", "09:00"), RecordedCall("tool:now", "{}", "09:05")]
        )

        assert [recording.answer("tool:now", {}) for _ in range(3)] == [
            RecordedCall("tool:now", "{}", "09:00"),
            RecordedCall("tool:now", "{}", "09:05"),
            None,
        ]

    def test_argument_order_does_not_count_but_a_value_does(self):
        recording = ToolRecording([RecordedCall("tool:get", normalized_args({"a": 1, "b": 2}), 1)])

        assert recording.answer("tool:get", {"b": 2, "a": 999}) is None
        assert recording.answer("tool:get", {"b": 2, "a": 1}) is not None


class TestACallTheAgentGates:
    """An isolated run cannot ask anyone, and the refusal would leave no trace."""

    async def test_a_gated_read_is_held_and_recorded_as_needing_approval(self):
        world = _World()
        isolation = RunIsolation()
        agent = Agent(
            _calls_then_answers(("crm_find", {"name": "Ada"})),
            deps_type=AgentDeps,
            capabilities=[
                IsolationGuard(isolation=isolation, approval=ApprovalGate(gate_every_tool=True))
            ],
            toolsets=[world.toolset("crm_find", test=False, read_only=True)],
        )

        result = await agent.run("go", deps=AgentDeps())

        assert world.effects == []
        assert [(c.outcome, c.reason) for c in isolation.intercepted] == [
            (InterceptionOutcome.BLOCKED, InterceptionReason.NEEDS_APPROVAL)
        ]
        assert "approve" in result.output

    async def test_a_write_is_recorded_as_a_write_whether_or_not_it_is_gated(self):
        isolation = RunIsolation()
        guard = IsolationGuard(isolation=isolation, approval=ApprovalGate(gate_every_tool=True))

        await guard.wrap_tool_execute(
            AsyncMock(),
            call=ToolCallPart(tool_name="send", args={}, tool_call_id="c"),
            tool_def=ToolDefinition(name="send"),
            args={},
            handler=AsyncMock(),
        )

        assert isolation.intercepted[0].reason is InterceptionReason.WRITES

    async def test_an_ungated_read_runs(self):
        handler = AsyncMock(return_value="found")
        guard = IsolationGuard(isolation=RunIsolation(), approval=ApprovalGate())

        result = await guard.wrap_tool_execute(
            AsyncMock(),
            call=ToolCallPart(tool_name="load_capability", args={}, tool_call_id="c"),
            tool_def=ToolDefinition(name="load_capability"),
            args={},
            handler=handler,
        )

        assert result == "found"

    async def test_a_replayed_call_answers_even_where_the_agent_gates_it(self):
        """Nothing is executed, so there is nothing to approve."""
        isolation = RunIsolation(recording=ToolRecording([RecordedCall("tool:send", "{}", "sent")]))
        guard = IsolationGuard(isolation=isolation, approval=ApprovalGate(gate_every_tool=True))

        result = await guard.wrap_tool_execute(
            AsyncMock(),
            call=ToolCallPart(tool_name="send", args={}, tool_call_id="c"),
            tool_def=ToolDefinition(name="send"),
            args={},
            handler=AsyncMock(),
        )

        assert result == "sent"


def _model_spec() -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid.uuid4(),
        label="GPT-4.1",
        provider="openai",
        model="gpt-4.1",
        params={},
        credential=ResolvedCredential(
            provider="openai", secret=ApiKeySecret(api_key="sk-test-key")
        ),
        fallbacks=[],
    )


class TestTheFactory:
    async def test_an_isolated_agent_records_a_write_the_approval_gate_would_have_asked_about(
        self,
    ):
        """The guard sits in front of the gate: an eval has nobody to ask, and a
        write it holds is an intended call, not a refusal."""
        world = _World()
        isolation = RunIsolation()
        ask = AsyncMock()
        built = build_agent(
            AgentSpec(name="Support", instructions="Help."),
            _model_spec(),
            organization_id=uuid.uuid4(),
            extra_toolsets=[world.toolset("crm_create", test=False, read_only=False)],
            request_approval=ask,
            gate_every_tool=True,
            isolation=isolation,
        )

        with built.agent.override(model=_calls_then_answers(("crm_create", {"name": "Ada"}))):
            await built.agent.run("go", deps=built.deps)

        assert built.deps.request_approval is None
        ask.assert_not_awaited()
        assert world.effects == []
        assert [call.outcome for call in isolation.intercepted] == [InterceptionOutcome.BLOCKED]

    async def test_an_ordinary_agent_is_not_isolated(self):
        world = _World()
        built = build_agent(
            AgentSpec(name="Support", instructions="Help."),
            _model_spec(),
            organization_id=uuid.uuid4(),
            extra_toolsets=[world.toolset("crm_create", test=False, read_only=False)],
        )

        with built.agent.override(model=_calls_then_answers(("crm_create", {"name": "Ada"}))):
            await built.agent.run("go", deps=built.deps)

        assert world.effects == [("crm_create", "Ada")]

    async def test_the_guard_asks_the_agents_own_gate(self):
        """The spec's gate, not a copy: a read the agent gates is held as one."""
        world = _World()
        isolation = RunIsolation()
        built = build_agent(
            AgentSpec(name="Support", instructions="Help."),
            _model_spec(),
            organization_id=uuid.uuid4(),
            extra_toolsets=[world.toolset("crm_find", test=False, read_only=True)],
            gate_every_tool=True,
            isolation=isolation,
        )

        with built.agent.override(model=_calls_then_answers(("crm_find", {"name": "Ada"}))):
            await built.agent.run("go", deps=built.deps)

        assert world.effects == []
        assert [call.reason for call in isolation.intercepted] == [
            InterceptionReason.NEEDS_APPROVAL
        ]
