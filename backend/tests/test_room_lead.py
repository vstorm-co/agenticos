"""Only human review can turn the room lead's bounded proposal into executable work."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FunctionToolset

from app.agents.deps import AgentDeps
from app.agents.room_lead import PROPOSE_ROOM_TASKS, RoomLeadPlanning, planning_spec
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import AuthorizationError, BadRequestError
from app.schemas.room_routing import (
    RoomLeadPolicyWrite,
    RoomProposalAccept,
    RoomProposalCreate,
    RoomProposalItem,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def item(**changes):
    return RoomProposalItem.model_validate(
        {
            "title": "Prepare a draft",
            "expected_result": "A draft for human review",
            "agent_id": uuid4(),
            "agent_version_id": uuid4(),
            **changes,
        }
    )


def test_planning_keeps_the_published_voice_and_guardrails_but_removes_executable_resources():
    guard = CapabilityBindingSpec(id="guardrails")
    spec = AgentSpec(
        name="Lead",
        instructions="Be concise",
        capabilities=[guard, CapabilityBindingSpec(id="web_search")],
        collection_ids=[uuid4()],
        skill_ids=[uuid4()],
        context_ids=[uuid4()],
        code_mode={"enabled": True},
    )
    result = planning_spec(spec)
    assert result.instructions == spec.instructions and result.context_ids == spec.context_ids
    assert result.capabilities == [guard]
    assert result.collection_ids == result.skill_ids == result.mcp_servers == result.subagents == []
    assert not result.code_mode.enabled and result.output_schema is None
    assert len(spec.capabilities) == 2 and spec.code_mode.enabled


async def test_real_agent_sees_only_the_pending_proposal_tool_and_never_external_actions():
    request = item()
    proposal_id, item_id, run_id = uuid4(), uuid4(), uuid4()
    writer = AsyncMock(
        return_value=SimpleNamespace(
            id=proposal_id, items=[SimpleNamespace(proposal_item_id=item_id)]
        )
    )
    capability = RoomLeadPlanning(
        context="Pinned policy for this explicit request", create_proposal=writer
    )
    sent = MagicMock()
    tools = FunctionToolset()

    def send_external_message() -> str:
        sent()
        return "sent"

    tools.add_function(send_external_message)
    seen = []

    def scripted(messages, info):
        seen.append({tool.name for tool in info.function_tools})
        returned = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        if not returned:
            return ModelResponse(
                parts=[
                    ToolCallPart(PROPOSE_ROOM_TASKS, {"items": [request.model_dump(mode="json")]})
                ]
            )
        assert "Pending proposal" in str(returned[-1].content)
        return ModelResponse(parts=[TextPart("The proposal is ready for human review.")])

    agent = Agent(
        FunctionModel(scripted), deps_type=AgentDeps, capabilities=[capability], toolsets=[tools]
    )
    result = await agent.run("Plan this handoff", deps=AgentDeps(run_id=run_id))
    assert "human review" in result.output
    assert seen and all(names == {PROPOSE_ROOM_TASKS} for names in seen)
    sent.assert_not_called()
    writer.assert_awaited_once_with(run_id, RoomProposalCreate(items=[request]))


async def test_unexpected_tool_execution_is_refused_even_if_a_tool_bypasses_preparation():
    capability = RoomLeadPlanning(context="policy", create_proposal=AsyncMock())
    handler = AsyncMock(return_value="sent")
    result = await capability.wrap_tool_execute(
        SimpleNamespace(),
        call=ToolCallPart("send_external_message", {}),
        tool_def=ToolDefinition(name="send_external_message"),
        args={},
        handler=handler,
    )
    assert "only answer or propose" in result
    handler.assert_not_awaited()


async def test_missing_run_identity_cannot_save_a_proposal():
    writer = AsyncMock()
    capability = RoomLeadPlanning(context="policy", create_proposal=writer)
    result = await capability.propose_room_tasks(SimpleNamespace(deps=AgentDeps()), [item()])
    assert "no proposal was saved" in result
    writer.assert_not_awaited()


@pytest.mark.parametrize(
    "error",
    [
        BadRequestError(message="Choose a pinned specialist"),
        AuthorizationError(message="private internal context"),
    ],
)
async def test_model_argument_corrections_and_authority_refusals_are_reported_without_internal_context(
    error,
):
    capability = RoomLeadPlanning(context="policy", create_proposal=AsyncMock(side_effect=error))
    result = await capability.propose_room_tasks(
        SimpleNamespace(deps=AgentDeps(run_id=uuid4()), last_attempt=True), [item()]
    )
    assert "private internal context" not in result
    assert (
        result == "Choose a pinned specialist"
        if isinstance(error, BadRequestError)
        else "unavailable" in result
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"existing_task_id": uuid4()},
        {"expected_task_revision": 1},
        {"conversation_id": uuid4()},
        {"outcome_id": uuid4()},
        {"status": "done"},
        {"title": " "},
        {"expected_result": ""},
        {"expected_result": " "},
    ],
)
def test_proposal_items_refuse_unreviewable_or_forged_task_fields(changes):
    with pytest.raises(ValidationError):
        item(**changes)


def test_policy_and_review_contracts_refuse_duplicate_or_unbounded_selection():
    agent = uuid4()
    with pytest.raises(ValidationError):
        RoomLeadPolicyWrite(expected_revision=0, enabled=True)
    with pytest.raises(ValidationError):
        RoomLeadPolicyWrite(expected_revision=0, enabled=False, specialist_agent_ids=[agent, agent])
    with pytest.raises(ValidationError):
        RoomLeadPolicyWrite(expected_revision=0, enabled=False, max_items=4)
    with pytest.raises(ValidationError):
        RoomProposalCreate(items=[item() for _ in range(4)])
    selected = uuid4()
    with pytest.raises(ValidationError):
        RoomProposalAccept(
            expected_revision=1, idempotency_key="review", selected_item_ids=[selected, selected]
        )
