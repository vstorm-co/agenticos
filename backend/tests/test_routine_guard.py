"""A revoked routine never reaches its tool handler, including an approved replay."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FunctionToolset

from app.agents.approval import ApprovalGranted, ApprovalRequest
from app.agents.factory import build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.routine_authority import RoutineGuard, guard_for
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError
from app.core.secret_kinds import ApiKeySecret

pytestmark = pytest.mark.anyio


async def test_revocation_between_tools_refuses_the_next_effect() -> None:
    agent_id = uuid4()
    check = AsyncMock(side_effect=[None, AuthorizationError(message="Routine paused")])
    handler = AsyncMock(return_value="written")
    guard = RoutineGuard(check=check, agent_id=agent_id)
    call = ToolCallPart(tool_name="write", args={"value": 1}, tool_call_id="one")

    async def invoke() -> object:
        return await guard.wrap_tool_execute(
            MagicMock(spec=RunContext),
            call=call,
            tool_def=ToolDefinition(name="write"),
            args={"value": 1},
            handler=handler,
        )

    assert await invoke() == "written"
    refused = await invoke()
    assert "Routine paused" in str(refused)
    handler.assert_awaited_once_with({"value": 1})
    assert check.await_count == 2
    check.assert_awaited_with(agent_id)


async def test_an_unexpected_authorization_failure_is_not_disguised_as_a_refusal() -> None:
    guard = RoutineGuard(
        check=AsyncMock(side_effect=RuntimeError("database down")), agent_id=uuid4()
    )
    handler = AsyncMock()
    with pytest.raises(RuntimeError, match="database down"):
        await guard.wrap_tool_execute(
            MagicMock(spec=RunContext),
            call=ToolCallPart(tool_name="write", args={}),
            tool_def=ToolDefinition(name="write"),
            args={},
            handler=handler,
        )
    handler.assert_not_awaited()


def test_only_a_routine_gets_the_runtime_wrapper() -> None:
    agent_id = uuid4()
    assert guard_for(None, agent_id=agent_id) == ()
    check = AsyncMock()
    wrappers = guard_for(check, agent_id=agent_id)
    assert len(wrappers) == 1 and wrappers[0].check is check


@pytest.mark.security
async def test_factory_checks_authority_after_waiting_for_approval_and_before_the_effect() -> None:
    revoked = False
    effects: list[str] = []

    async def check(agent_id: UUID) -> None:
        if revoked:
            raise AuthorizationError(message="Routine paused while approval was pending")

    async def approve(request: ApprovalRequest) -> ApprovalGranted:
        nonlocal revoked
        revoked = True
        return ApprovalGranted(tool_args=request.tool_args)

    async def write() -> str:
        effects.append("written")
        return "written"

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if any(isinstance(part, ToolReturnPart) for message in messages for part in message.parts):
            return ModelResponse(parts=[TextPart("Finished")])
        return ModelResponse(
            parts=[ToolCallPart(tool_name="write", args={}, tool_call_id="write-1")]
        )

    request = ModelRequestSpec(
        profile_id=uuid4(),
        label="Test",
        provider="openai",
        model="gpt-4.1",
        params={},
        fallbacks=[],
        credential=ResolvedCredential(
            provider="openai", secret=ApiKeySecret(api_key="sk-test-key")
        ),
    )
    tools = FunctionToolset()
    tools.add_function(write)
    built = build_agent(
        AgentSpec(name="Routine"),
        request,
        organization_id=uuid4(),
        agent_id=uuid4(),
        extra_toolsets=[tools],
        extra_capabilities=guard_for(check, agent_id=uuid4()),
        gate_every_tool=True,
        request_approval=approve,
    )
    with built.agent.override(model=FunctionModel(respond)):
        result = await built.agent.run("Write", deps=built.deps)
    assert effects == [] and revoked
    assert "Routine paused while approval was pending" in str(result.all_messages())
