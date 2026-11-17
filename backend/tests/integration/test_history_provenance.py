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
