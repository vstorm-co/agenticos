"""Real Monty feeds resumed through the platform approval gate."""

import json

import pytest
from pydantic_ai import Agent, AgentRunResult, RunContext
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

from app.agents.approval import (
    ApprovalDecision,
    ApprovalGranted,
    ApprovalPending,
    ApprovalRejected,
    ApprovalRequest,
)
from app.agents.capabilities.approval._capability import ApprovalGate
from app.agents.code_checkpoint import CodeCheckpoint
from app.agents.code_mode import CodeCalls, code_mode
from app.agents.deps import AgentDeps
from app.agents.manifest import RunRecorder
from app.agents.mcp import NEEDS_APPROVAL
from app.agents.tool_errors import ToolErrors

pytestmark = pytest.mark.anyio


@pytest.mark.security
@pytest.mark.parametrize("max_calls", [5, 10])
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("reject", [None, 5])
async def test_ten_gated_writes_resume_with_no_model_turns(
    reject: int | None, parallel: bool, max_calls: int
) -> None:
    script = 'answers=[]\nfor i in range(10):\n    try:\n        answers.append(await write(i=i))\n    except RuntimeError:\n        answers.append("rejected")\nanswers'
    if parallel:
        script = 'import asyncio\nasync def one(i):\n    try:\n        return await write(i=i)\n    except RuntimeError:\n        return "rejected"\nawait asyncio.gather(*[one(i) for i in range(10)])'
    effects: list[int] = []
    asked: dict[str, ApprovalRequest] = {}
    decisions: dict[str, bool] = {}
    requests = 0
    toolset = FunctionToolset[AgentDeps](id="writes")

    @toolset.tool(metadata={NEEDS_APPROVAL: True})
    async def write(ctx: RunContext[AgentDeps], i: int) -> int:
        effects.append(i)
        return i * 2

    async def approve(request: ApprovalRequest) -> ApprovalDecision:
        asked[request.tool_call_id] = request
        decision = decisions.get(request.tool_call_id)
        if decision is None:
            return ApprovalPending()
        return ApprovalGranted(request.tool_args) if decision else ApprovalRejected("no")

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        if any(isinstance(part, ToolReturnPart) for message in messages for part in message.parts):
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[ToolCallPart("run_code", {"code": script}, tool_call_id="script")]
        )

    history: list[ModelMessage] = []
    checkpoints: dict[str, CodeCheckpoint] = {}
    replay: DeferredToolResults | None = None
    for index in range(max_calls + 1):
        deps = AgentDeps(request_approval=approve)
        deps.code_continuations.checkpoints.update(checkpoints)
        recorder = RunRecorder()
        agent = Agent[AgentDeps, str | DeferredToolRequests](
            FunctionModel(model),
            output_type=str | DeferredToolRequests,
            toolsets=[toolset],
            capabilities=[
                ApprovalGate(required_tool_names=frozenset({"write"})),
                code_mode(
                    approval_required=frozenset({"write"}),
                    asking=frozenset(),
                    max_tool_calls=max_calls,
                ),
                CodeCalls(recorder),
            ],
        )
        result = await agent.run(
            "write" if not history else None,
            deps=deps,
            message_history=history,
            deferred_tool_results=replay,
        )
        history = ModelMessagesTypeAdapter.validate_json(
            ModelMessagesTypeAdapter.dump_json(result.all_messages())
        )
        checkpoints = {
            key: CodeCheckpoint.model_validate(json.loads(value.model_dump_json()))
            for key, value in deps.code_continuations.checkpoints.items()
        }
        if index == max_calls:
            assert result.output == "done"
            assert not checkpoints
        else:
            assert isinstance(result.output, DeferredToolRequests), (
                effects,
                asked,
                result.all_messages_json().decode(),
            )
            assert requests == 1
            assert [part.tool_call_id for part in result.output.approvals] == ["script"]
            pending = [key for key in asked if key not in decisions]
            assert len(pending) == 1
            decisions[pending[0]] = asked[pending[0]].tool_args["i"] != reject
            replay = DeferredToolResults(approvals={"script": ToolApproved()})
    assert requests == 2
    assert sorted(effects) == [index for index in range(max_calls) if index != reject]


@pytest.mark.parametrize("damage", ["runtime", "format", "code_hash", "snapshot", "tool"])
async def test_an_unrestorable_checkpoint_never_runs_an_approved_tool(damage: str) -> None:
    effects: list[int] = []
    tools = FunctionToolset[AgentDeps]()

    @tools.tool_plain(metadata={NEEDS_APPROVAL: True})
    def write(i: int) -> int:
        effects.append(i)
        return i

    approved = False

    async def ask(request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalGranted(request.tool_args) if approved else ApprovalPending()

    def model(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart("run_code", {"code": "await write(i=1)"}, tool_call_id="script")
                ]
            )
        return ModelResponse(parts=[TextPart("done")])

    def build() -> Agent[AgentDeps, str | DeferredToolRequests]:
        return Agent[AgentDeps, str | DeferredToolRequests](
            FunctionModel(model),
            output_type=str | DeferredToolRequests,
            toolsets=[tools],
            capabilities=[
                ApprovalGate(),
                code_mode(approval_required=frozenset(), asking=frozenset(), max_tool_calls=5),
                CodeCalls(RunRecorder()),
            ],
        )

    deps = AgentDeps(request_approval=ask)
    first = await build().run("write", deps=deps)
    assert isinstance(first.output, DeferredToolRequests)
    saved = CodeCheckpoint.model_validate_json(
        deps.code_continuations.checkpoints["script"].model_dump_json()
    )
    if damage == "tool":
        saved.calls[0].tool_name = "removed_tool"
    else:
        saved = saved.model_copy(update={damage: 99 if damage == "format" else "invalid"})
    approved = True
    resumed_deps = AgentDeps(request_approval=ask)
    resumed_deps.code_continuations.checkpoints["script"] = saved
    result = await build().run(
        None,
        deps=resumed_deps,
        message_history=first.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={"script": ToolApproved()}),
    )
    assert not effects
    returns = [
        part
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert returns[0].outcome == "failed"
    assert "No pending tool ran" in str(returns[0].content)


class _Script:
    """A fresh agent/worker and JSON-round-tripped state for every segment."""

    def __init__(self, code: str, *, sequential: bool = False) -> None:
        self.code = code
        self.effects: list[int] = []
        self.reads: list[int] = []
        self.active = 0
        self.peak = 0
        self.allowed = True
        self.failure: Exception | None = None
        self.gate = ApprovalGate()
        self.requests = 0
        self.pending: dict[str, ApprovalRequest] = {}
        self.decisions: dict[str, ApprovalGranted | ApprovalRejected] = {}
        self.history: list[ModelMessage] = []
        self.saved: dict[str, CodeCheckpoint] = {}
        self.recorder = RunRecorder()
        self.tools = FunctionToolset[AgentDeps]()
        self.tools.add_function(
            self.write,
            name="write",
            takes_ctx=False,
            metadata={NEEDS_APPROVAL: True},
            sequential=sequential,
        )
        self.tools.add_function(self.read, name="read", takes_ctx=False)

    async def write(self, i: int) -> int:
        if self.failure is not None:
            raise self.failure
        if not self.allowed:
            raise PermissionError("Access was revoked")
        self.effects.append(i)
        return i

    async def read(self, i: int) -> bytes:
        import anyio

        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await anyio.sleep(0.01)
            self.reads.append(i)
            return f"done{i}".encode()
        finally:
            self.active -= 1

    async def ask(
        self, request: ApprovalRequest
    ) -> ApprovalGranted | ApprovalRejected | ApprovalPending:
        if (decision := self.decisions.pop(request.tool_call_id, None)) is not None:
            return decision
        self.pending[request.tool_call_id] = request
        return ApprovalPending()

    def approve(self) -> None:
        for key, request in self.pending.items():
            self.decisions[key] = ApprovalGranted(request.tool_args)
        self.pending.clear()

    def respond(self, messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        self.requests += 1
        if len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart("run_code", {"code": self.code}, tool_call_id="script")]
            )
        return ModelResponse(parts=[TextPart("done")])

    async def step(self, *, quota: int = 100) -> AgentRunResult[str | DeferredToolRequests]:
        from pydantic_ai.usage import UsageLimits

        deps = AgentDeps(request_approval=self.ask)
        deps.code_continuations.checkpoints.update(self.saved)
        self.recorder = RunRecorder()
        agent = Agent[AgentDeps, str | DeferredToolRequests](
            FunctionModel(self.respond),
            output_type=str | DeferredToolRequests,
            toolsets=[self.tools],
            capabilities=[
                ToolErrors(),
                self.gate,
                code_mode(approval_required=frozenset(), asking=frozenset(), max_tool_calls=100),
                CodeCalls(self.recorder),
            ],
        )
        result = await agent.run(
            "work" if not self.history else None,
            deps=deps,
            message_history=self.history,
            deferred_tool_results=None
            if not self.history
            else DeferredToolResults(approvals={"script": ToolApproved()}),
            usage_limits=UsageLimits(tool_calls_limit=quota),
        )
        self.history = ModelMessagesTypeAdapter.validate_json(
            ModelMessagesTypeAdapter.dump_json(result.all_messages())
        )
        self.saved = {
            key: CodeCheckpoint.model_validate_json(value.model_dump_json())
            for key, value in deps.code_continuations.checkpoints.items()
        }
        return result


async def test_parking_drains_started_reads_and_preserves_binary_results() -> None:
    script = _Script(
        'import asyncio\nresults = await asyncio.gather(read(i=0), write(i=0), read(i=1), read(i=2), read(i=3), read(i=4))\nresults[0] == b"done0"'
    )
    first = await script.step()
    assert isinstance(first.output, DeferredToolRequests)
    assert script.active == 0
    assert script.reads
    assert not script.effects
    assert any(call.settled for call in script.saved["script"].calls)
    script.approve()
    result = await script.step()
    assert result.output == "done"
    assert script.effects == [0]
    assert sorted(script.reads) == list(range(5))
    assert script.peak <= 4
    assert script.active == 0
    assert script.requests == 2
    returned = [
        part
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert returned[0].content is True


@pytest.mark.security
async def test_permissions_are_rechecked_after_the_approval() -> None:
    script = _Script('try:\n    await write(i=1)\nexcept RuntimeError:\n    "refused"')
    assert isinstance((await script.step()).output, DeferredToolRequests)
    script.allowed = False
    script.approve()
    assert (await script.step()).output == "done"
    assert not script.effects
    (record,) = script.recorder.code_runs
    assert record["calls"][0]["status"] == "failed"


@pytest.mark.security
async def test_the_global_tool_budget_is_not_replenished_by_approvals() -> None:
    from pydantic_ai.exceptions import UsageLimitExceeded

    script = _Script(
        "for i in range(10):\n    try:\n        await write(i=i)\n    except RuntimeError:\n        pass"
    )
    for _ in range(3):
        assert isinstance((await script.step(quota=4)).output, DeferredToolRequests)
        script.approve()
    with pytest.raises(UsageLimitExceeded):
        await script.step(quota=4)
    assert script.effects == [0, 1, 2]
    assert script.requests == 1


@pytest.mark.security
def test_resume_routes_inner_approvals_to_their_own_script_and_delegate() -> None:
    from app.agents.code_checkpoint import CodeHostCall
    from app.services.agent_runner import DelegationFrame, PausedRunState, _resume_plan

    def checkpoint(parent: str, inner: str, task: str | None) -> CodeCheckpoint:
        return CodeCheckpoint(
            parent_tool_call_id=parent,
            task_id=task,
            runtime="test",
            code_hash="test",
            snapshot_hash="test",
            snapshot="test",
            call_count=1,
            calls=[CodeHostCall(monty_id=1, tool_call_id=inner, tool_name="write", args={})],
            history=[],
            content={},
            printed="",
            manifest={},
        )

    root = checkpoint("script", "script__1", None)
    child = checkpoint("script", "delegate/script__1", "delegate")
    messages = json.loads(
        ModelMessagesTypeAdapter.dump_json(
            [
                ModelResponse(
                    parts=[ToolCallPart("run_code", {"code": "pass"}, tool_call_id="script")]
                )
            ]
        )
    )
    state = PausedRunState(
        messages=messages,
        tool_call_ids={"a": "script__1", "b": "delegate/script__1"},
        delegated_approvals={"b": "delegate"},
        code_checkpoints={"script": root, "delegate/script": child},
        delegations=[
            DelegationFrame(
                tool_call_id="task-call", task_id="delegate", subagent="writer", messages=messages
            )
        ],
    )
    kept = PausedRunState.model_validate_json(state.model_dump_json())
    plan = _resume_plan(kept, {"script__1": {"i": 1}, "delegate/script__1": {"i": 2}})
    assert set(plan.results.approvals) == {"script", "task-call"}
    assert plan.results.approvals["script"] == ToolApproved()
    assert plan.delegations["task-call"].results.approvals == {"script": ToolApproved()}
    # Approval of the outer call contains no write arguments and cannot waive a child gate.
    assert all(
        value.override_args is None
        for value in plan.results.approvals.values()
        if isinstance(value, ToolApproved)
    )
    legacy = PausedRunState.model_validate({"messages": [], "tool_call_ids": {"a": "old-write"}})
    assert not legacy.code_checkpoints
    assert _resume_plan(legacy, {"old-write": {"i": 3}}).results.approvals == {
        "old-write": ToolApproved(override_args={"i": 3})
    }


def test_subagents_share_checkpoint_storage_with_the_parent() -> None:
    deps = AgentDeps()
    child = deps.clone_for_subagent()
    assert child.code_continuations is deps.code_continuations


@pytest.mark.security
async def test_delegate_checkpoint_identity_and_frozen_approval_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.capabilities.subagents import _journal
    from app.agents.capabilities.subagents._journal import ActingDelegate

    monkeypatch.setattr(
        _journal,
        "acting_delegate",
        lambda: ActingDelegate(name="writer", task_id="delegate-A", agent_id=None, depth=1),
    )
    script = _Script("await write(i=1)")
    assert isinstance((await script.step()).output, DeferredToolRequests)
    assert set(script.saved) == {"delegate-A/script"}
    assert set(script.pending) == {"delegate-A/script__1"}
    script.decisions["delegate-A/script__1"] = ApprovalGranted({"i": 99})
    script.pending.clear()
    assert (await script.step()).output == "done"
    assert script.effects == [99]
    assert script.requests == 2


def test_a_resumed_manifest_replaces_the_partial_script_without_losing_other_scripts() -> None:
    from app.agents.manifest import carried_over

    before = {"tool_call_id": "first", "code": "work", "calls": [{"status": "awaiting_approval"}]}
    after = {"tool_call_id": "first", "code": "work", "calls": [{"status": "returned"}]}
    other = {"tool_call_id": "other", "code": "more", "calls": []}
    assert carried_over({"code_runs": [before, other]}, {"code_runs": [after]})["code_runs"] == [
        after,
        other,
    ]


async def test_a_sequential_tool_continues_at_the_saved_function_call() -> None:
    script = _Script(
        'print("before")\nfirst = write(i=1)\nsecond = write(i=2)\nprint("after")\n[first, second]',
        sequential=True,
    )
    for _ in range(2):
        assert isinstance((await script.step()).output, DeferredToolRequests)
        script.approve()
    result = await script.step()
    assert result.output == "done"
    assert script.effects == [1, 2]
    assert script.requests == 2
    returns = [
        part
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert returns[0].content == {"output": "before\nafter\n", "result": [1, 2]}


@pytest.mark.parametrize("code", ["if", "1 / 0", "await write(i=1)\nunknown_name"])
async def test_sandbox_errors_with_governed_tools_keep_the_normal_failure_contract(
    code: str,
) -> None:
    script = _Script(code)
    result = await script.step()
    if isinstance(result.output, DeferredToolRequests):
        script.approve()
        result = await script.step()
    assert result.output == "done"
    returns = [
        part
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert returns[-1].outcome == "failed"
    assert "error" in str(returns[-1].content)


@pytest.mark.security
async def test_a_rotated_mcp_source_cannot_use_the_old_approval() -> None:
    from uuid import uuid4

    from app.agents.mcp import MCP_ORIGIN, McpSourceIdentity, McpToolOrigin

    script = _Script("await write(i=1)")
    connection = uuid4()
    authorization = uuid4()
    script.tools.tools["write"].metadata = {
        NEEDS_APPROVAL: True,
        MCP_ORIGIN: McpToolOrigin(
            connection, McpSourceIdentity("old-endpoint", authorization), "write"
        ),
    }
    assert isinstance((await script.step()).output, DeferredToolRequests)
    script.approve()
    script.tools.tools["write"].metadata = {
        NEEDS_APPROVAL: True,
        MCP_ORIGIN: McpToolOrigin(
            connection, McpSourceIdentity("other-endpoint", authorization), "write"
        ),
    }
    result = await script.step()
    assert result.output == "done"
    assert not script.effects
    returns = [
        part
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert "No pending tool ran" in str(returns[0].content)


def test_checkpoint_values_survive_json_without_confusing_user_data_with_tags() -> None:
    from app.agents.durable_code import _pack, _unpack

    original = {
        "payload": [b"\x00\xff", {"kind": "bytes", "value": "user text"}],
        "empty": None,
        "tuple": (1, [2], (b"three",)),
    }
    assert _unpack(json.loads(json.dumps(_pack(original)))) == original
    with pytest.raises(TypeError, match="not a sandbox value"):
        _pack(object())
    with pytest.raises(ValueError, match="Invalid persisted"):
        _unpack(["unknown", "tag"])


@pytest.mark.parametrize("limit", ["_MAX_SNAPSHOT", "_MAX_CHECKPOINT_BYTES"])
async def test_checkpoint_size_limits_fail_without_executing_the_pending_write(
    monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    from app.agents import durable_code

    monkeypatch.setattr(durable_code, limit, 1)
    script = _Script("await write(i=1)")
    result = await script.step()
    assert result.output == "done"
    assert not script.effects
    assert not script.saved
    returns = [
        part
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert "limit" in str(returns[0].content)


@pytest.mark.parametrize(
    "damage", ["checksum", "missing", "duplicate", "result", "counter", "history"]
)
async def test_corrupt_host_state_is_refused_before_dispatch(damage: str) -> None:
    script = _Script("await write(i=1)")
    assert isinstance((await script.step()).output, DeferredToolRequests)
    saved = script.saved["script"]
    if damage == "checksum":
        saved.snapshot_hash = "different"
    elif damage == "missing":
        saved.calls.clear()
    elif damage == "duplicate":
        saved.calls.append(saved.calls[0].model_copy(deep=True))
    elif damage == "counter":
        saved.call_count = 0
    elif damage == "history":
        saved.history.extend(
            json.loads(
                ModelMessagesTypeAdapter.dump_json([ModelResponse(parts=[TextPart("invalid")])])
            )
        )
    else:
        saved.calls[0].settled = True
        saved.calls[0].value = ["invalid", "result"]
    script.approve()
    result = await script.step()
    assert result.output == "done"
    assert not script.effects
    returns = [
        part
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert "No pending tool ran" in str(returns[0].content)


@pytest.mark.parametrize(
    "code",
    [
        "import time\ntime.sleep(0)\nawait write(i=1)",
        "import asyncio\nawait asyncio.sleep(0)\nawait write(i=1)",
        "import time\ntry:\n    time.sleep(31)\nexcept RuntimeError:\n    pass\nawait write(i=1)",
    ],
)
@pytest.mark.security
async def test_sleeps_remain_bounded_with_an_approval_checkpoint(code: str) -> None:
    script = _Script(code)
    assert isinstance((await script.step()).output, DeferredToolRequests)
    script.approve()
    assert (await script.step()).output == "done"
    assert script.effects == [1]


async def test_a_governed_script_keeps_the_sandbox_filesystem_closed() -> None:
    script = _Script('from pathlib import Path\nPath("/etc/passwd").read_text()\nawait write(i=1)')
    result = await script.step()
    assert result.output == "done"
    assert not script.effects
    assert not script.pending
    returns = [
        part
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert "permission_denied" in str(returns[0].content)


async def test_global_sequential_execution_survives_a_checkpoint() -> None:
    from pydantic_ai.tool_manager import ToolManager

    script = _Script(
        "import asyncio\nawait asyncio.gather(read(i=0), read(i=1), write(i=1), read(i=2))"
    )
    with ToolManager.parallel_execution_mode("sequential"):
        assert isinstance((await script.step()).output, DeferredToolRequests)
        script.approve()
        assert (await script.step()).output == "done"
    assert script.effects == [1]
    assert script.peak == 1


@pytest.mark.security
async def test_an_input_guardrail_still_blocks_an_approved_nested_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai_harness import _code_tools

    script = _Script("try:\n    await write(i=1)\nexcept RuntimeError:\n    pass")
    assert isinstance((await script.step()).output, DeferredToolRequests)
    script.approve()

    async def blocked(_ctx: RunContext[AgentDeps]) -> bool:
        return False

    monkeypatch.setattr(_code_tools, "input_guardrails_allow", blocked)
    assert (await script.step()).output == "done"
    assert not script.effects


@pytest.mark.security
async def test_binary_arguments_survive_the_approval_checkpoint() -> None:
    script = _Script("payload = await read(i=0)\nawait blob(payload=payload)")
    received: list[bytes] = []

    async def blob(payload: bytes) -> int:
        received.append(payload)
        return len(payload)

    script.tools.add_function(blob, name="blob", takes_ctx=False, metadata={NEEDS_APPROVAL: True})
    assert isinstance((await script.step()).output, DeferredToolRequests)
    assert received == []
    script.approve()
    assert (await script.step()).output == "done"
    assert received == [b"done0"]
    assert script.reads == [0]


@pytest.mark.security
async def test_a_read_only_hint_change_cannot_bypass_a_recorded_rejection() -> None:
    script = _Script("await write(i=1)")
    assert isinstance((await script.step()).output, DeferredToolRequests)
    for key in script.pending:
        script.decisions[key] = ApprovalRejected("Rejected by reviewer")
    script.pending.clear()
    script.tools.tools["write"].metadata = {NEEDS_APPROVAL: False}
    result = await script.step()
    assert result.output == "done"
    assert script.effects == []


@pytest.mark.parametrize("failure", ["budget", "guardrail"])
async def test_run_stops_cannot_be_caught_and_ignored_inside_the_script(failure: str) -> None:
    from decimal import Decimal

    from app.agents.capabilities.budget import BudgetExceeded, BudgetScope
    from app.agents.capabilities.guardrails import GuardrailBlocked

    script = _Script("try:\n    await write(i=1)\nexcept RuntimeError:\n    await write(i=2)")
    assert isinstance((await script.step()).output, DeferredToolRequests)
    script.approve()
    script.failure = (
        BudgetExceeded(limit_usd=Decimal("1"), spent_usd=Decimal("1"), scope=BudgetScope.AGENT)
        if failure == "budget"
        else GuardrailBlocked(edge="tool", message="blocked")
    )
    with pytest.raises(type(script.failure)):
        await script.step()
    assert not script.effects
    assert script.requests == 1


async def test_an_unhandled_tool_quota_error_remains_a_run_stop() -> None:
    from pydantic_ai.exceptions import UsageLimitExceeded

    script = _Script("for i in range(3):\n    await write(i=i)")
    for _ in range(2):
        assert isinstance((await script.step(quota=3)).output, DeferredToolRequests)
        script.approve()
    with pytest.raises(UsageLimitExceeded):
        await script.step(quota=3)
    assert script.effects == [0, 1]


@pytest.mark.security
async def test_a_concurrent_quota_stop_outweighs_an_approval_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import anyio
    from pydantic_ai.exceptions import UsageLimitExceeded

    from app.agents.code_checkpoint import CodeHostCall
    from app.agents.durable_code import _Feed

    script = _Script("import asyncio\nawait asyncio.gather(write(i=1), read(i=0), read(i=2))")
    ask = script.ask
    quota_stopped = anyio.Event()
    call = _Feed._call

    async def observed(feed: _Feed, host_call: CodeHostCall) -> None:
        await call(feed, host_call)
        if feed.execution.usage_limit_exceeded is not None:
            quota_stopped.set()

    async def delayed(request: ApprovalRequest) -> ApprovalDecision:
        # Establish the competing outcome before parking, independent of CI scheduling.
        await quota_stopped.wait()
        return await ask(request)

    monkeypatch.setattr(_Feed, "_call", observed)
    monkeypatch.setattr(script, "ask", delayed)
    with anyio.fail_after(5), pytest.raises(UsageLimitExceeded):
        await script.step(quota=3)
    assert not script.effects
    assert script.active == 0
    assert script.requests == 1


async def test_a_pending_async_call_is_drained_before_a_sequential_barrier() -> None:
    script = _Script("pending = write(i=1)\nread(i=0)\nawait pending")
    script.tools.tools["read"].sequential = True
    assert isinstance((await script.step()).output, DeferredToolRequests)
    assert not script.reads
    script.approve()
    assert (await script.step()).output == "done"
    assert script.effects == [1]
    assert script.reads == [0]


async def test_a_caught_filesystem_refusal_does_not_gain_access_on_resume() -> None:
    script = _Script(
        'from pathlib import Path\ntry:\n    Path("/etc/passwd").read_text()\nexcept PermissionError:\n    pass\nawait write(i=1)'
    )
    assert isinstance((await script.step()).output, DeferredToolRequests)
    script.approve()
    assert (await script.step()).output == "done"
    assert script.effects == [1]


@pytest.mark.parametrize(
    ("code", "failed"),
    [
        ("unknown_name", True),
        ("await write(1)", True),
        ("try:\n    await write(1)\nexcept TypeError:\n    pass", False),
    ],
)
async def test_later_feeds_validate_runtime_names_and_keyword_arguments(
    monkeypatch: pytest.MonkeyPatch, code: str, failed: bool
) -> None:
    script = _Script(code)

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        script.requests += 1
        if script.requests == 1:
            return ModelResponse(
                parts=[ToolCallPart("run_code", {"code": "seed=1"}, tool_call_id="seed")]
            )
        if script.requests == 2:
            return ModelResponse(
                parts=[ToolCallPart("run_code", {"code": code}, tool_call_id="script")]
            )
        return ModelResponse(parts=[TextPart("done")])

    monkeypatch.setattr(script, "respond", respond)
    assert (await script.step()).output == "done"
    assert script.effects == []
    assert script.requests == 3
    returns = [
        part
        for message in script.history
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert (returns[-1].outcome == "failed") is failed


@pytest.mark.parametrize("sequential", [False, True])
async def test_deferred_sleeps_and_governed_calls_keep_their_state(sequential: bool) -> None:
    from contextlib import nullcontext

    from pydantic_ai.tool_manager import ToolManager

    script = _Script("import asyncio\nawait asyncio.gather(asyncio.sleep(0), write(i=1))")
    with ToolManager.parallel_execution_mode("sequential") if sequential else nullcontext():
        assert isinstance((await script.step()).output, DeferredToolRequests)
        script.approve()
        assert (await script.step()).output == "done"
    assert script.effects == [1]


async def test_a_valid_monty_snapshot_at_the_wrong_position_is_not_a_continuation() -> None:
    import base64
    import hashlib

    from pydantic_monty import AsyncMonty, AsyncNameLookupSnapshot

    script = _Script("await write(i=1)")
    assert isinstance((await script.step()).output, DeferredToolRequests)
    async with AsyncMonty(max_processes=1) as pool, pool.checkout(type_check=False) as session:
        progress = await session.feed_start("unknown_name", skip_type_check=True)
        assert isinstance(progress, AsyncNameLookupSnapshot)
        raw = progress.dump()
    script.saved["script"].snapshot = base64.b64encode(raw).decode()
    script.saved["script"].snapshot_hash = hashlib.sha256(raw).hexdigest()
    script.approve()
    result = await script.step()
    assert result.output == "done"
    assert not script.effects
    returns = [
        part
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert "No pending tool ran" in str(returns[0].content)


@pytest.mark.security
async def test_a_script_without_an_approval_channel_refuses_the_gated_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _Script("await write(i=1)")
    monkeypatch.setattr(script, "ask", None)
    result = await script.step()
    assert result.output == "done"
    assert not script.effects
    returns = [
        part
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert returns[0].outcome == "failed"


async def test_routine_authorization_refusals_remain_script_errors() -> None:
    from pydantic_ai.tools import ToolDefinition

    from app.agents.routine_actions import RoutineToolDecision
    from app.core.exceptions import AuthorizationError

    script = _Script("await write(i=1)")

    async def policy(tool: ToolDefinition) -> RoutineToolDecision:
        if tool.name == "write":
            raise AuthorizationError(message="Access revoked")
        return RoutineToolDecision()

    script.gate.routine_policy = policy
    assert (await script.step()).output == "done"
    assert not script.effects


@pytest.mark.parametrize("same_agent", [False, True])
async def test_parallel_scripts_keep_the_latest_usage_without_borrowing_delegate_limits(
    same_agent: bool,
) -> None:
    from pydantic_ai.exceptions import UsageLimitExceeded

    script = _Script("await write(i=1)")
    assert isinstance((await script.step(quota=4)).output, DeferredToolRequests)
    script.approve()
    script.saved["other"] = script.saved["script"].model_copy(
        update={
            "parent_tool_call_id": "other",
            "task_id": None if same_agent else "delegate",
            "usage_calls": 3 if same_agent else 1000,
        }
    )
    if same_agent:
        with pytest.raises(UsageLimitExceeded):
            await script.step(quota=4)
        assert not script.effects
    else:
        assert (await script.step(quota=4)).output == "done"
        assert script.effects == [1]


async def test_an_interpreter_restore_failure_does_not_expose_snapshot_bytes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import base64
    import hashlib

    script = _Script("await write(i=1)")
    assert isinstance((await script.step()).output, DeferredToolRequests)
    raw = b"server-private-invalid-interpreter-state"
    saved = script.saved["script"]
    saved.snapshot = base64.b64encode(raw).decode()
    saved.snapshot_hash = hashlib.sha256(raw).hexdigest()
    script.approve()
    result = await script.step()
    assert result.output == "done"
    assert not script.effects
    assert "server-private-invalid-interpreter-state" not in caplog.text
    assert saved.snapshot not in caplog.text
    returns = [
        part
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert "No pending tool ran" in str(returns[0].content)


async def test_changing_sequential_execution_invalidates_a_checkpoint() -> None:
    script = _Script("await write(i=1)")
    assert isinstance((await script.step()).output, DeferredToolRequests)
    script.tools.tools["write"].sequential = True
    script.approve()
    assert (await script.step()).output == "done"
    assert not script.effects


@pytest.mark.parametrize(
    "module, duration",
    [
        ("time", "-100"),
        ("time", "float('nan')"),
        ("time", "float('inf')"),
        ("asyncio", "-100"),
        ("asyncio", "float('nan')"),
    ],
)
@pytest.mark.security
async def test_invalid_sleep_cannot_credit_the_persisted_budget(module: str, duration: str) -> None:
    import anyio

    operation = "await asyncio.sleep" if module == "asyncio" else "time.sleep"
    script = _Script(
        f"import {module}\ntry:\n    {operation}({duration})\nexcept (ValueError, OverflowError):\n    pass\nawait write(i=1)"
    )
    with anyio.fail_after(2):
        assert isinstance((await script.step()).output, DeferredToolRequests)
    assert script.saved["script"].slept_secs == 0
    script.approve()
    assert (await script.step()).output == "done"
    assert script.effects == [1]
