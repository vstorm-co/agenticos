"""Resolved model changes cannot receive a private checkpoint from an earlier turn."""

import pytest
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.model_resolver import ModelRequestSpec
from app.agents.spec import AgentSpec
from app.db.models.conversation import Conversation
from app.db.models.credential import ModelProfile
from app.services.agent_runner import AgentRunnerService
from app.services.conversation import ConversationService
from tests.integration.test_platform_flows import _keyed_model_profile, _published_agent, _tenant
from tests.test_history_audience_privacy import hidden_exchange

pytestmark = pytest.mark.anyio


@pytest.mark.security
@pytest.mark.parametrize("change", ["unchanged", "agent", "endpoint", "override", "fallback"])
async def test_private_tools_follow_the_resolved_destination_across_real_runs(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    received: list[str] = []

    async def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        received.append(ModelMessagesTypeAdapter.dump_json(messages).decode())
        return ModelResponse(parts=[TextPart("VISIBLE_ANSWER")])

    monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(respond))
    tenant = await _tenant(db, name="History destinations")
    model = await _keyed_model_profile(db, tenant)
    agent = await _published_agent(
        db, tenant, spec=AgentSpec(name="Private reader", model_profile_id=model.id)
    )
    chat = Conversation(user_id=tenant.user.id, organization_id=tenant.organization.id)
    db.add(chat)
    await db.flush()
    service = ConversationService(db)
    initial = await service.model_history(chat.id, limit=50)
    await AgentRunnerService(db).execute(
        tenant.ctx, agent.id, "VISIBLE_QUESTION", conversation_id=chat.id, message_history=initial
    )
    await db.refresh(chat)
    assert isinstance(chat.summary_messages, dict)
    original_provenance = chat.summary_messages["provenance"]
    chat.summary_messages = {
        **chat.summary_messages,
        "messages": [
            *chat.summary_messages["messages"],
            *ModelMessagesTypeAdapter.dump_python(hidden_exchange(), mode="json"),
        ],
    }
    await db.commit()
    # Load the checkpoint first, exactly as the web and channel surfaces do.
    history = await service.model_history(chat.id, limit=50)
    assert "PRIVATE_EVENT_THERAPY" in ModelMessagesTypeAdapter.dump_json(history).decode()
    override = None
    if change == "agent":
        agent = await _published_agent(
            db, tenant, spec=AgentSpec(name="Other reader", model_profile_id=model.id)
        )
    elif change == "endpoint":
        model.base_url = "https://another-gateway.example/v1"
    elif change in {"override", "fallback"}:
        other = ModelProfile(
            organization_id=tenant.organization.id,
            label="Other destination",
            provider="openai",
            model="gpt-4.1",
            secret_id=model.secret_id,
        )
        db.add(other)
        await db.flush()
        if change == "override":
            override = other.id
        else:
            model.fallback_profile_ids = [str(other.id)]
    await db.flush()
    await AgentRunnerService(db).execute(
        tenant.ctx,
        agent.id,
        "Follow up",
        conversation_id=chat.id,
        message_history=history,
        model_profile_id=override,
    )
    assert ("PRIVATE_EVENT_THERAPY" in received[-1]) is (change == "unchanged")
    assert "VISIBLE_QUESTION" in received[-1] and "VISIBLE_ANSWER" in received[-1]
    await db.refresh(chat)
    assert isinstance(chat.summary_messages, dict)
    assert (chat.summary_messages["provenance"] == original_provenance) is (change == "unchanged")


@pytest.mark.security
async def test_a_legacy_private_checkpoint_is_not_copied_into_a_new_fork(
    db: AsyncSession,
) -> None:
    from app.core.permissions import AuthContext
    from tests.integration.test_conversation_fork import _source, _turn

    source = await _source(db)
    answer = await _turn(db, source, "assistant", "VISIBLE_ANSWER")
    source.summary_messages = ModelMessagesTypeAdapter.dump_python(hidden_exchange(), mode="json")
    source.summary_ordinal = answer.ordinal
    await db.flush()
    fork = await ConversationService(db).fork(
        source.id,
        message_id=answer.id,
        organization_id=source.organization_id,
        user_id=source.user_id,
        ctx=AuthContext(
            user_id=source.user_id, organization_id=source.organization_id, role="owner"
        ),
    )
    assert fork.summary_messages is None and fork.summary_ordinal is None
    history = await ConversationService(db).model_history(fork.id, limit=50)
    text = ModelMessagesTypeAdapter.dump_json(history).decode()
    assert "PRIVATE_EVENT_THERAPY" not in text and "VISIBLE_ANSWER" in text


@pytest.mark.security
@pytest.mark.parametrize("change", ["unchanged", "endpoint", "generation", "disabled"])
async def test_private_tool_replay_is_bound_to_live_mcp_connection_metadata(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from uuid import uuid4

    from pydantic_ai.toolsets import FunctionToolset

    from app.agents.mcp import McpServerSpec
    from app.agents.spec import OrgMcpServerRef
    from tests.integration.test_platform_flows import _mcp_connection

    async def probe(
        specs: list[McpServerSpec],
    ) -> list[tuple[McpServerSpec, FunctionToolset[object]]]:
        return [(spec, FunctionToolset()) for spec in specs]

    monkeypatch.setattr("app.services.mcp_connection.probe_toolsets", probe)
    received: list[str] = []

    async def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        received.append(ModelMessagesTypeAdapter.dump_json(messages).decode())
        return ModelResponse(parts=[TextPart("VISIBLE_ANSWER")])

    monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(respond))
    tenant = await _tenant(db, name="Live MCP history")
    model = await _keyed_model_profile(db, tenant)
    connection = await _mcp_connection(db, tenant, name="records", scope="org")
    agent = await _published_agent(
        db,
        tenant,
        spec=AgentSpec(
            name="Reader",
            model_profile_id=model.id,
            mcp_servers=[OrgMcpServerRef(connection_id=connection.id)],
        ),
    )
    chat = Conversation(user_id=tenant.user.id, organization_id=tenant.organization.id)
    db.add(chat)
    await db.flush()
    service = ConversationService(db)
    initial = await service.model_history(chat.id, limit=50)
    await AgentRunnerService(db).execute(
        tenant.ctx, agent.id, "VISIBLE_QUESTION", conversation_id=chat.id, message_history=initial
    )
    await db.refresh(chat)
    assert isinstance(chat.summary_messages, dict)
    original = chat.summary_messages["provenance"]
    assert original["mcp_destination_digest"] is not None
    chat.summary_messages = {
        **chat.summary_messages,
        "messages": [
            *chat.summary_messages["messages"],
            *ModelMessagesTypeAdapter.dump_python(hidden_exchange(), mode="json"),
        ],
    }
    await db.commit()
    history = await service.model_history(chat.id, limit=50)
    if change == "endpoint":
        connection.url = "https://other-mcp.example/mcp"
    elif change == "generation":
        connection.authorization_generation = uuid4()
    elif change == "disabled":
        connection.is_enabled = False
    await db.flush()
    await AgentRunnerService(db).execute(
        tenant.ctx, agent.id, "Follow up", conversation_id=chat.id, message_history=history
    )
    assert ("PRIVATE_EVENT_THERAPY" in received[-1]) is (change == "unchanged")
    assert "VISIBLE_QUESTION" in received[-1] and "VISIBLE_ANSWER" in received[-1]
    await db.refresh(chat)
    assert isinstance(chat.summary_messages, dict)
    current = chat.summary_messages["provenance"]
    assert current["configuration_digest"] == original["configuration_digest"]
    assert (current["mcp_destination_digest"] == original["mcp_destination_digest"]) is (
        change == "unchanged"
    )


@pytest.mark.security
async def test_a_parked_run_refuses_changed_live_mcp_before_rebuilding_the_agent(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    from pydantic_ai.messages import ModelRequest, ToolCallPart, UserPromptPart
    from pydantic_ai.toolsets import FunctionToolset

    from app.agents.mcp import McpServerSpec
    from app.agents.spec import OrgMcpServerRef
    from app.core.exceptions import BadRequestError
    from app.db.models.agent_run import RunStatus, RunSurface
    from app.services.agent_runner import PausedRunState
    from tests.integration.test_platform_flows import _mcp_connection

    async def probe(
        specs: list[McpServerSpec],
    ) -> list[tuple[McpServerSpec, FunctionToolset[object]]]:
        return [(spec, FunctionToolset()) for spec in specs]

    async def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise AssertionError("A changed MCP destination must not reach the model")

    monkeypatch.setattr("app.services.mcp_connection.probe_toolsets", probe)
    monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(respond))
    tenant = await _tenant(db, name="Parked MCP history")
    model = await _keyed_model_profile(db, tenant)
    connection = await _mcp_connection(db, tenant, name="records", scope="org")
    agent = await _published_agent(
        db,
        tenant,
        spec=AgentSpec(
            name="Reader",
            model_profile_id=model.id,
            mcp_servers=[OrgMcpServerRef(connection_id=connection.id)],
        ),
    )
    runner = AgentRunnerService(db)
    prepared = await runner.prepare(tenant.ctx, agent.id, surface=RunSurface.WEB)
    question = {
        "questions": [
            {
                "header": "Tone",
                "question": "How formal?",
                "options": [{"label": "Formal"}, {"label": "Casual"}],
            }
        ]
    }
    state = PausedRunState(
        messages=ModelMessagesTypeAdapter.dump_python(
            [
                *hidden_exchange(),
                ModelRequest(parts=[UserPromptPart("Draft a reply")]),
                ModelResponse(
                    parts=[ToolCallPart("ask_user_question", question, tool_call_id="ask-1")]
                ),
            ],
            mode="json",
        ),
        tool_call_ids={},
        questions=["ask-1"],
    )
    await runner.finish(prepared, status=RunStatus.AWAITING_ANSWER, paused_state=state)
    await db.commit()
    connection.url = "https://changed-mcp.example/mcp"
    await db.commit()
    build = MagicMock()
    monkeypatch.setattr("app.services.agent_runner.build_agent", build)
    with pytest.raises(BadRequestError) as refused:
        await runner.resume(tenant.ctx, prepared.run.id, answers={"ask-1": {"Tone": ["Formal"]}})
    assert refused.value.details == {"code": "HISTORY_DESTINATION_CHANGED"}
    build.assert_not_called()
    await db.refresh(prepared.run)
    assert prepared.run.status == RunStatus.AWAITING_ANSWER.value
