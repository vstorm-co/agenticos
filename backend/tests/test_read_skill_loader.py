"""Skill-specific vocabulary retains native disclosure and history replay."""

import json
from collections.abc import AsyncIterator

import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import Capability
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import (
    LoadCapabilityCallPart,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities.skills._loader import (
    ReadSkillCallPart,
    ReadSkillReturnPart,
    SkillLoader,
    _skill_message,
)
from app.agents.ephemeral_media import dump_messages

pytestmark = pytest.mark.anyio


def _skill() -> Capability[None]:
    tools = FunctionToolset()

    @tools.tool_plain
    def check_order() -> str:
        """Check an order."""
        return "checked"

    return Capability(
        id="refunds",
        description="Refund policy",
        instructions="PRIVATE_POLICY",
        defer_loading=True,
        toolsets=[tools],
    )


def _read_then_finish(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    names = {tool.name for tool in info.function_tools}
    assert "load_capability" not in names
    if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
        assert "check_order" in names
        return ModelResponse(parts=[TextPart("done")])
    assert "check_order" not in names
    return ModelResponse(parts=[ToolCallPart("read_skill", {"id": "refunds"})])


async def test_native_activation_and_typed_history_roundtrip():
    agent = Agent(FunctionModel(_read_then_finish), capabilities=[SkillLoader(), _skill()])
    result = await agent.run("Refund")
    stored = dump_messages(result.all_messages())
    assert any(
        isinstance(part, ReadSkillCallPart)
        for message in result.all_messages()
        for part in message.parts
    )
    instruction_ids = [
        part["id"]
        for message in stored
        for part in message["parts"]
        if part["part_kind"] == "instruction-delta"
    ]
    assert "capability:refunds" in instruction_ids
    assert "Available skills:" in json.dumps(stored)
    assert "The following capabilities are deferred" not in json.dumps(stored)
    history = ModelMessagesTypeAdapter.validate_python(stored)
    calls = [p for m in history for p in m.parts if isinstance(p, LoadCapabilityCallPart)]
    assert len(calls) == 1 and isinstance(calls[0], ReadSkillCallPart)
    assert calls[0].tool_name == "read_skill"
    assert any(isinstance(p, ReadSkillReturnPart) for m in history for p in m.parts)
    assert "PRIVATE_POLICY" in json.dumps(stored)
    assert (await agent.run("Continue", message_history=history)).output == "done"


async def test_legacy_native_history_stays_loaded():
    def old_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(parts=[ToolCallPart("load_capability", {"id": "refunds"})])

    old = await Agent(FunctionModel(old_model), capabilities=[_skill()]).run("Refund")
    history = ModelMessagesTypeAdapter.validate_python(dump_messages(old.all_messages()))
    new = Agent(FunctionModel(_read_then_finish), capabilities=[SkillLoader(), _skill()])
    assert (await new.run("Continue", message_history=history)).output == "done"


@pytest.mark.parametrize("ids", [["missing"], ["refunds", "refunds"]])
async def test_native_refusals_use_skill_vocabulary(ids):
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if returns:
            errors = [p for p in returns if p.outcome != "success"]
            assert len(errors) == 1
            assert "capability" not in str(errors[0].content).lower()
            assert "skill" in str(errors[0].content).lower()
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[ToolCallPart("read_skill", {"id": skill_id}) for skill_id in ids]
        )

    result = await Agent(FunctionModel(respond), capabilities=[SkillLoader(), _skill()]).run(
        "Refund"
    )
    assert result.output == "done"


async def test_streaming_native_load_is_serializable():
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            yield "done"
        else:
            yield {0: DeltaToolCall(name="read_skill", json_args='{"id":"refunds"}')}

    agent = Agent(FunctionModel(stream_function=stream), capabilities=[SkillLoader(), _skill()])
    async with agent.run_stream("Refund") as result:
        assert await result.get_output() == "done"
    assert ModelMessagesTypeAdapter.validate_python(dump_messages(result.all_messages()))


async def test_adapter_does_not_overwrite_a_tool():
    tools = FunctionToolset()

    @tools.tool_plain
    def read_skill() -> str:
        """Conflicting tool."""
        return "wrong"

    with pytest.raises(UserError, match="reserved"):
        await Agent(
            FunctionModel(_read_then_finish),
            capabilities=[SkillLoader(), _skill()],
            toolsets=[tools],
        ).run("Refund")


def test_framework_text_preserves_a_skill_id_containing_the_old_tool_name():
    skill_id = "`load_capability`"
    assert (
        _skill_message(f"Capability {skill_id!r} loaded.", skill_id)
        == f"Skill {skill_id!r} loaded."
    )
    assert _skill_message("unrecognized error", skill_id) == "unrecognized error"


@pytest.mark.security
async def test_old_pending_approval_resumes_with_the_same_call_id_and_arguments():
    from unittest.mock import AsyncMock

    from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolApproved

    from app.agents.capabilities.approval import ApprovalGate, ApprovalGranted, ApprovalPending
    from app.agents.deps import AgentDeps

    def old_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart("load_capability", {"id": "refunds"}, tool_call_id="pending-skill")]
        )

    old = Agent(
        FunctionModel(old_model),
        output_type=[str, DeferredToolRequests],
        capabilities=[_skill(), ApprovalGate(required_tool_names=frozenset({"load_capability"}))],
    )
    parked = await old.run(
        "Refund", deps=AgentDeps(request_approval=AsyncMock(return_value=ApprovalPending()))
    )
    assert isinstance(parked.output, DeferredToolRequests)
    assert "PRIVATE_POLICY" not in json.dumps(dump_messages(parked.all_messages()))
    approval = AsyncMock(return_value=ApprovalGranted(tool_args={"id": "refunds"}))
    new = Agent(
        FunctionModel(_read_then_finish),
        output_type=[str, DeferredToolRequests],
        capabilities=[
            SkillLoader(),
            _skill(),
            ApprovalGate(required_tool_names=frozenset({"read_skill"})),
        ],
    )
    resumed = await new.run(
        message_history=ModelMessagesTypeAdapter.validate_python(
            dump_messages(parked.all_messages())
        ),
        deferred_tool_results=DeferredToolResults(approvals={"pending-skill": ToolApproved()}),
        deps=AgentDeps(request_approval=approval),
    )
    assert resumed.output == "done"
    asked = approval.await_args.args[0]
    assert asked.tool_call_id == "pending-skill"
    assert asked.tool_name == "read_skill"
    assert asked.tool_args == {"id": "refunds"}


async def test_other_tools_still_execute_after_loading():
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        results = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        if not results:
            return ModelResponse(parts=[ToolCallPart("read_skill", {"id": "refunds"})])
        if len(results) == 1:
            return ModelResponse(parts=[ToolCallPart("check_order", {})])
        assert results[-1].content == "checked"
        return ModelResponse(parts=[TextPart("done")])

    assert (
        await Agent(FunctionModel(respond), capabilities=[SkillLoader(), _skill()]).run("Refund")
    ).output == "done"


@pytest.mark.security
def test_old_approval_policy_names_the_new_loader():
    from app.agents.capabilities import load_builtins
    from app.agents.capabilities.approval import approval_required_tools, approval_tool_ids
    from app.agents.spec import AgentSpec

    load_builtins()
    spec = AgentSpec(
        name="Support",
        capabilities=[{"id": "skills", "tool_approval": {"load_capability": "required"}}],
    )
    assert approval_required_tools(spec) == {"read_skill"}
    assert approval_tool_ids(spec)["read_skill"] == "load_capability"


@pytest.mark.security
async def test_a_remembered_skill_cannot_bypass_fresh_approval():
    from pydantic_ai.messages import CapabilityLoadDeltaPart, ModelRequest

    from app.agents.capabilities.approval import ApprovalGate
    from app.agents.deps import AgentDeps

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert "PRIVATE_POLICY" not in repr(messages)
        assert "PRIVATE_POLICY" not in (info.instructions or "")
        if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[TextPart("refused")])
        return ModelResponse(parts=[ToolCallPart("read_skill", {"id": "refunds"})])

    agent = Agent(
        FunctionModel(respond),
        capabilities=[
            SkillLoader(),
            _skill(),
            ApprovalGate(required_tool_names=frozenset({"read_skill"})),
        ],
    )
    history = [
        ModelRequest(
            parts=[
                CapabilityLoadDeltaPart(loaded=["refunds"], tool_call_id="agenticos:restored-loads")
            ]
        )
    ]
    result = await agent.run("Refund", deps=AgentDeps(), message_history=history)
    assert result.output == "refused"


@pytest.mark.security
async def test_supporting_files_stay_separate_and_require_reading_the_skill():
    from types import SimpleNamespace

    from app.agents.capabilities.skills import Skills

    stored = SimpleNamespace(
        name="refunds",
        description="Refund policy",
        content="Use its template.",
        resources=[
            SimpleNamespace(name="reply.md", description="Reply template", content="TEMPLATE_BODY")
        ],
    )
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        resource = next(t for t in info.function_tools if t.name == "read_skill_resource")
        assert "load_capability" not in resource.description
        assert "capability catalog" not in repr(resource.parameters_json_schema)
        if calls in (1, 3):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "read_skill_resource",
                        {"skill_name": "refunds", "resource_name": "reply.md"},
                    )
                ]
            )
        returned = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)][-1]
        if calls == 2:
            assert "Call read_skill" in str(returned.content)
            assert "load_capability" not in str(returned.content)
            assert "TEMPLATE_BODY" not in repr(messages)
            return ModelResponse(parts=[ToolCallPart("read_skill", {"id": "refunds"})])
        assert returned.content == "TEMPLATE_BODY"
        return ModelResponse(parts=[TextPart("done")])

    result = await Agent(
        FunctionModel(respond), capabilities=[SkillLoader(), Skills([stored])]
    ).run("Refund")
    assert result.output == "done"


@pytest.mark.parametrize(
    "case", ["missing_skill", "invalid_skill", "other_error", "feedback", "structured_error"]
)
async def test_unrelated_retry_signals_are_preserved(case: str):
    from pydantic_ai import RunContext
    from pydantic_ai.exceptions import ToolRetryError
    from pydantic_ai.messages import RetryFeedbackPart, RetryInfo
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.tools import ToolDefinition
    from pydantic_ai.usage import RunUsage

    args = (
        {}
        if case == "missing_skill"
        else {"skill_name": 42 if case == "invalid_skill" else "refunds"}
    )
    part = (
        RetryFeedbackPart("retry", retry=RetryInfo(cause="model_retry"))
        if case == "feedback"
        else ToolReturnPart(
            "other",
            [{"type": "value_error", "loc": (), "msg": "invalid", "input": 0}]
            if case == "structured_error"
            else "unrelated failure",
            outcome="retried",
        )
    )
    signal = ToolRetryError(part)

    async def handler(args):
        raise signal

    with pytest.raises(ToolRetryError) as caught:
        await SkillLoader().wrap_tool_execute(
            RunContext(deps=None, model=TestModel(), usage=RunUsage()),
            call=ToolCallPart("other", args),
            tool_def=ToolDefinition(name="other"),
            args=args,
            handler=handler,
        )
    assert caught.value is signal


async def test_the_toolset_can_forward_an_existing_tool():
    from pydantic_ai import RunContext
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.usage import RunUsage

    from app.agents.capabilities.skills._loader import _SkillLoaderToolset

    tools = FunctionToolset()

    @tools.tool_plain
    def clock() -> str:
        """Read the clock."""
        return "now"

    ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
    original = (await tools.get_tools(ctx))["clock"]
    assert await _SkillLoaderToolset(wrapped=tools).call_tool("clock", {}, ctx, original) == "now"


async def test_code_mode_keeps_the_native_skill_loader_directly_available():
    from app.agents.code_mode import code_mode

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        names = {tool.name for tool in info.function_tools}
        assert "read_skill" in names
        if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            assert "run_code" in names
            assert "PRIVATE_POLICY" in repr(messages)
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(parts=[ToolCallPart("read_skill", {"id": "refunds"})])

    agent = Agent(
        FunctionModel(respond),
        capabilities=[
            SkillLoader(),
            _skill(),
            code_mode(approval_required=frozenset(), asking=frozenset(), max_tool_calls=10),
        ],
    )
    assert (await agent.run("Refund")).output == "done"
