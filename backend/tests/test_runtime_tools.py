"""Native tools preserve the prepared run's validation and capability wrappers."""

from dataclasses import replace

import pytest
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models.test import TestModel
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage

from app.agents.deps import AgentDeps
from app.agents.runtime_tools import RuntimeTools

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def bridge(*, secrets: tuple[str, ...] = ()) -> tuple[RuntimeTools, list[int]]:
    calls: list[int] = []
    tools = FunctionToolset[AgentDeps]()

    @tools.tool_plain
    def increment(value: int) -> dict[str, int]:
        """Record an admitted integer."""
        calls.append(value)
        return {"value": value + 1}

    ctx = RunContext(deps=AgentDeps(), model=TestModel(), usage=RunUsage())
    ctx.tool_manager = ToolManager(
        toolset=tools,
        root_capability=AbstractCapability(),
        ctx=ctx,
        tools=await tools.get_tools(ctx),
    )
    return RuntimeTools(ctx, secrets=secrets), calls


async def test_only_prepared_tool_definitions_are_visible_and_arguments_are_validated() -> None:
    runtime, calls = await bridge()
    catalog = await runtime.dispatch("_agenticos/tools/list", {})
    assert catalog["tools"][0]["name"] == "increment"
    assert "value" in catalog["tools"][0]["inputSchema"]["properties"]
    result = await runtime.dispatch(
        "_agenticos/tools/call", {"name": "increment", "arguments": {"value": 2}}
    )
    assert result["isError"] is False and calls == [2]
    refused = await runtime.dispatch(
        "_agenticos/tools/call", {"name": "increment", "arguments": {"value": "invalid"}}
    )
    assert refused["isError"] is True and calls == [2]
    with pytest.raises(ValueError, match="unavailable"):
        await runtime.dispatch("_agenticos/tools/call", {"name": "not_in_this_run"})
    with pytest.raises(ValueError, match="Unsupported"):
        await runtime.dispatch("_agenticos/admin", {})


async def test_native_delegation_is_excluded_even_when_renamed() -> None:
    runtime, calls = await bridge()
    tool = runtime._parent.tools["increment"]
    runtime._parent.tools["increment"] = replace(
        tool, tool_def=replace(tool.tool_def, capability_id="external_acp")
    )
    isolated = RuntimeTools(runtime._ctx)
    assert await isolated.dispatch("_agenticos/tools/list", {}) == {"tools": []}
    with pytest.raises(ValueError, match="unavailable"):
        await isolated.dispatch(
            "_agenticos/tools/call", {"name": "increment", "arguments": {"value": 1}}
        )
    assert not calls


async def test_selected_credentials_never_enter_platform_tool_arguments() -> None:
    runtime, calls = await bridge(secrets=("a-private-key",))
    with pytest.raises(ValueError, match="Credential"):
        await runtime.dispatch(
            "_agenticos/tools/call", {"name": "increment", "arguments": {"value": "a-private-key"}}
        )
    assert not calls


async def test_platform_validation_execution_and_result_hooks_are_not_bypassed() -> None:
    runtime, calls = await bridge()
    root = runtime._parent.root_capability
    original = root.wrap_tool_execute
    seen: list[str] = []

    async def wrap(ctx, *, call, tool_def, args, handler):
        seen.append(call.tool_name)
        result = await original(ctx, call=call, tool_def=tool_def, args=args, handler=handler)
        return {"screened": result}

    root.wrap_tool_execute = wrap
    result = await runtime.dispatch(
        "_agenticos/tools/call", {"name": "increment", "arguments": {"value": 3}}
    )
    assert calls == [3] and seen == ["increment"]
    assert "screened" in result["content"][0]["text"]


async def test_a_missing_prepared_manager_is_an_explicit_refusal() -> None:
    ctx = RunContext(deps=AgentDeps(), model=TestModel(), usage=RunUsage())
    with pytest.raises(ValueError, match="prepared"):
        RuntimeTools(ctx)


async def test_native_tool_calls_share_the_parent_usage_limit() -> None:
    from pydantic_ai.exceptions import UsageLimitExceeded
    from pydantic_ai.usage import UsageLimits

    runtime, calls = await bridge()
    runtime._ctx.usage_limits = UsageLimits(tool_calls_limit=1)
    await runtime.dispatch(
        "_agenticos/tools/call", {"name": "increment", "arguments": {"value": 1}}
    )
    assert runtime._ctx.usage.tool_calls == 1
    with pytest.raises(UsageLimitExceeded):
        await runtime.dispatch(
            "_agenticos/tools/call", {"name": "increment", "arguments": {"value": 2}}
        )
    assert calls == [1]


@pytest.mark.parametrize("approved", [False, True])
async def test_native_mcp_approval_uses_validated_arguments_before_any_execution(
    approved: bool,
) -> None:
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4

    from app.agents.approval import ApprovalGranted, ApprovalRejected

    runtime, calls = await bridge()
    runtime._ctx.deps.user_id = str(uuid4())
    runtime._ctx.deps.runtime_questions = AsyncMock()
    approvals = MagicMock()
    approvals.live = AsyncMock(
        return_value=ApprovalGranted({"value": 2}) if approved else ApprovalRejected()
    )
    runtime._ctx.deps.request_approval = approvals
    tool = runtime._parent.tools["increment"]
    runtime._parent.tools["increment"] = replace(
        tool, tool_def=replace(tool.tool_def, kind="unapproved")
    )
    runtime = RuntimeTools(runtime._ctx)
    result = await runtime.dispatch(
        "_agenticos/tools/call", {"name": "increment", "arguments": {"value": "2"}}
    )
    assert result["isError"] is not approved
    assert calls == ([2] if approved else [])
    approvals.live.assert_awaited_once()
    assert approvals.live.call_args.args[0].tool_args == {"value": 2}


async def test_acp_reverse_calls_dispatch_platform_tools_before_the_native_prompt_finishes() -> (
    None
):
    import anyio

    from app.agents.capabilities.coding_agent._acp import Conversation, _Collector
    from tests.test_coding_agent_acp import _nothing

    runtime, calls = await bridge()
    writer, reader = anyio.create_memory_object_stream[dict[str, object]](8)

    class Pipe:
        async def send(self, frame: dict[str, object]) -> None:
            if frame.get("method") == "session/prompt":
                await writer.send(
                    {
                        "jsonrpc": "2.0",
                        "id": "agenticos-bridge-one",
                        "method": "_agenticos/tools/call",
                        "params": {"name": "increment", "arguments": {"value": 7}},
                    }
                )
            elif frame.get("id") == "agenticos-bridge-one":
                assert frame["result"]["isError"] is False
                await writer.send({"jsonrpc": "2.0", "id": 1, "result": {"stopReason": "end_turn"}})

        async def receive(self) -> dict[str, object]:
            return await reader.receive()

        async def close(self) -> None:
            await writer.aclose()
            await reader.aclose()

    pipe = Pipe()
    conversation = Conversation(
        pipe, access="edit", collector=_Collector(), shown=_nothing, platform_tools=runtime
    )
    try:
        with anyio.fail_after(1):
            result = await conversation.request(
                "session/prompt", {"sessionId": "owned", "prompt": []}
            )
        assert result == {"stopReason": "end_turn"} and calls == [7]
    finally:
        await pipe.close()


async def test_pi_reverse_calls_keep_the_rpc_reader_live_until_the_platform_result_arrives() -> (
    None
):
    import anyio

    from app.agents.capabilities.external_acp._pi import run_pi
    from tests.test_pi_rpc import Pi, finished, ignore

    runtime, calls = await bridge()

    class ToolPi(Pi):
        def __init__(self) -> None:
            super().__init__(
                events=[
                    {
                        "jsonrpc": "2.0",
                        "id": "agenticos-bridge-two",
                        "method": "_agenticos/tools/call",
                        "params": {"name": "increment", "arguments": {"value": 8}},
                    }
                ]
            )
            self.ready = anyio.Event()

        async def send(self, frame: dict[str, object]) -> None:
            if frame.get("id") == "agenticos-bridge-two":
                assert frame["result"]["isError"] is False
                self.messages.extend([finished(), {"type": "agent_settled"}])
            else:
                await super().send(frame)
            self.ready.set()

        async def receive(self) -> dict[str, object]:
            while not self.messages:
                self.ready = anyio.Event()
                await self.ready.wait()
            return await super().receive()

    pipe = ToolPi()
    report = await run_pi(
        pipe, task="Work", timeout_seconds=1, shown=ignore, platform_tools=runtime
    )
    assert report.outcome == "completed" and calls == [8]
    assert pipe.closed


async def _custom_bridge(build) -> tuple[RuntimeTools, list[object]]:
    """A run whose single tool is defined by the test, with the bridge's deps."""
    seen: list[object] = []
    tools = FunctionToolset[AgentDeps]()
    build(tools, seen)
    ctx = RunContext(deps=AgentDeps(), model=TestModel(), usage=RunUsage())
    ctx.tool_manager = ToolManager(
        toolset=tools,
        root_capability=AbstractCapability(),
        ctx=ctx,
        tools=await tools.get_tools(ctx),
    )
    return RuntimeTools(ctx), seen


async def _call(runtime: RuntimeTools, name: str, arguments: dict[str, object]):
    return await runtime.dispatch("_agenticos/tools/call", {"name": name, "arguments": arguments})


async def test_oversized_native_arguments_are_refused_before_validation() -> None:
    runtime, calls = await bridge()
    with pytest.raises(ValueError, match="request limit"):
        await _call(runtime, "increment", {"value": 1, "padding": "x" * (130 << 10)})
    assert not calls


async def test_an_unapproved_action_without_a_live_surface_never_runs() -> None:
    runtime, calls = await bridge()
    tool = runtime._parent.tools["increment"]
    runtime._parent.tools["increment"] = replace(
        tool, tool_def=replace(tool.tool_def, kind="unapproved")
    )
    runtime = RuntimeTools(runtime._ctx)
    result = await _call(runtime, "increment", {"value": 1})
    assert result["isError"] is True and calls == []


async def test_a_nested_approval_must_repeat_the_exact_live_approval() -> None:
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4

    from app.agents.approval import ApprovalGranted, ApprovalRequest

    def build(tools: FunctionToolset[AgentDeps], seen: list[object]) -> None:
        @tools.tool
        async def send(ctx: RunContext[AgentDeps], value: int) -> str:
            """Send after confirming the exact action again."""
            decision = await ctx.deps.request_approval(
                ApprovalRequest(
                    capability_id=None,
                    tool_name="send",
                    tool_call_id="nested",
                    tool_args={"value": value if value < 10 else value + 1},
                )
            )
            seen.append(decision)
            return "sent"

    runtime, seen = await _custom_bridge(build)
    runtime._ctx.deps.user_id = str(uuid4())
    runtime._ctx.deps.runtime_questions = AsyncMock()
    approvals = MagicMock()
    approvals.live = AsyncMock(side_effect=lambda request, **_: ApprovalGranted(request.tool_args))
    runtime._ctx.deps.request_approval = approvals
    tool = runtime._parent.tools["send"]
    runtime._parent.tools["send"] = replace(
        tool, tool_def=replace(tool.tool_def, kind="unapproved")
    )
    runtime = RuntimeTools(runtime._ctx)
    same = await _call(runtime, "send", {"value": 2})
    assert same["isError"] is False and isinstance(seen[-1], ApprovalGranted)
    changed = await _call(runtime, "send", {"value": 12})
    assert changed["isError"] is True and "Do not claim" in changed["content"][0]["text"]


async def test_tool_questions_reach_the_live_chat_or_are_cancelled_without_one() -> None:
    from unittest.mock import AsyncMock

    from pydantic_ai_harness.ask_user import AskUserRequest, Question
    from pydantic_ai_harness.ask_user._types import QuestionOption

    from app.agents.runtime_questions import RuntimeAnswer, RuntimeQuestionResponse

    def build(tools: FunctionToolset[AgentDeps], seen: list[object]) -> None:
        @tools.tool
        async def choose(ctx: RunContext[AgentDeps]) -> str:
            """Ask which option to use."""
            response = await ctx.deps.ask_questions(
                AskUserRequest(
                    questions=(
                        Question(
                            header="Pick",
                            question="Which one?",
                            options=(
                                QuestionOption(label="A", description="first"),
                                QuestionOption(label="B", description="second"),
                            ),
                        ),
                    )
                )
            )
            seen.append(response)
            return "asked"

    runtime, seen = await _custom_bridge(build)
    assert (await _call(runtime, "choose", {}))["isError"] is False
    assert seen[-1].cancelled
    asked = AsyncMock(return_value=RuntimeQuestionResponse(answers=[RuntimeAnswer(selected=["B"])]))
    runtime._ctx.deps.runtime_questions = asked
    runtime = RuntimeTools(runtime._ctx)
    await _call(runtime, "choose", {})
    assert not seen[-1].cancelled
    assert asked.call_args.args[0].questions[0].question == "Which one?"
    asked.return_value = RuntimeQuestionResponse(cancelled=True)
    await _call(runtime, "choose", {})
    assert seen[-1].cancelled


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        ("deferred", "No approval or successful result"),
        ("refused", "Not allowed here"),
        ("content", "cannot represent"),
        ("huge", "exceeded the native bridge limit"),
    ],
)
async def test_unrepresentable_or_deferred_results_are_explicit_failures(
    outcome: str, message: str
) -> None:
    from pydantic_ai import CallDeferred, ToolReturn

    from app.core.exceptions import BadRequestError

    def build(tools: FunctionToolset[AgentDeps], seen: list[object]) -> None:
        @tools.tool_plain
        def act() -> object:
            """Do the thing."""
            if outcome == "deferred":
                raise CallDeferred
            if outcome == "refused":
                raise BadRequestError(message="Not allowed here")
            if outcome == "content":
                return ToolReturn(return_value="ok", content=["an image would be here"])
            return "x" * (3 << 20)

    runtime, _seen = await _custom_bridge(build)
    result = await _call(runtime, "act", {})
    assert result["isError"] is True and message in result["content"][0]["text"]


async def test_a_plain_tool_return_is_unwrapped_for_the_text_bridge() -> None:
    from pydantic_ai import ToolReturn

    def build(tools: FunctionToolset[AgentDeps], seen: list[object]) -> None:
        @tools.tool_plain
        def act() -> ToolReturn:
            """Return a wrapped value."""
            return ToolReturn(return_value={"done": True})

    runtime, _seen = await _custom_bridge(build)
    result = await _call(runtime, "act", {})
    assert result["isError"] is False and "done" in result["content"][0]["text"]
