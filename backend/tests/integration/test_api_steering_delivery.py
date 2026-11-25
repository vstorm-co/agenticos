"""A webhook arrives while the worker is waiting on a model, from a separate transaction."""

from uuid import UUID

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.model_resolver import ModelRequestSpec
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.permissions import AuthContext, Perm
from app.db.models.conversation import Message
from app.db.models.credential import ModelProfile
from app.schemas.agent import AgentRunRequest
from app.schemas.api_key import ApiKeyCreate
from app.services.agent_registry import AgentRegistryService
from app.services.api_key import ApiKeyService
from app.services.api_runs import ApiRunService
from tests.integration._keys import provider_key
from tests.integration.workflow_run_support import run_next_job, seed_member

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("another_step", [True, False], ids=["next-model-step", "last-model-step"])
async def test_webhook_correction_is_used_once(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, another_step: bool
) -> None:
    user, org = await seed_member(db)
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    profile = ModelProfile(
        organization_id=org.id,
        label="Default",
        provider="openai",
        model="gpt-4.1",
        secret_id=await provider_key(db, org.id),
    )
    db.add(profile)
    await db.flush()
    registry = AgentRegistryService(db)
    agent = await registry.create(
        ctx,
        AgentSpec(
            name="Analyst",
            model_profile_id=profile.id,
            capabilities=[CapabilityBindingSpec(id="planning")],
        ),
    )
    await registry.publish(ctx, agent.id)
    keys = ApiKeyService(db)
    issued = await keys.create(ctx, ApiKeyCreate(name="Webhook", scopes=[Perm.AGENTS_RUN]))
    webhook_ctx = (await keys.authenticate(issued.key)).context
    initial = await ApiRunService(db).queue(
        webhook_ctx, agent.id, AgentRunRequest(prompt="Write a forecast"), idempotency_key=None
    )
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    delivery_ids: list[UUID] = []
    seen: list[list[str]] = []
    correction = AgentRunRequest(
        conversation_id=initial.conversation_id, steer=True, prompt="Use the revised estimate"
    )

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(
            [
                str(part.content)
                for message in messages
                if isinstance(message, ModelRequest)
                for part in message.parts
                if isinstance(part, UserPromptPart)
            ]
        )
        if len(seen) == 1:
            # The first provider request is already in flight. Two independent webhook
            # deliveries of the same event must neither interrupt it nor create two turns.
            for _ in range(2):
                async with sessions.begin() as webhook:
                    receipt = await ApiRunService(webhook).queue(
                        webhook_ctx, agent.id, correction, idempotency_key="event-7"
                    )
                    delivery_ids.append(receipt.id)
            if another_step:
                return ModelResponse(parts=[ToolCallPart(tool_name="read_plan", args={})])
        revised = any(correction.prompt in words for words in seen[-1])
        return ModelResponse(
            parts=[TextPart("Revised forecast." if revised else "Original forecast.")]
        )

    monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(respond))
    assert await run_next_job(sessions, pool="agent")
    assert len(set(delivery_ids)) == 1
    service = ApiRunService(db)
    original = await service.get(webhook_ctx, initial.id)
    assert original.status == "completed" and original.result is not None
    receipt = await service.get(webhook_ctx, delivery_ids[0])
    if another_step:
        assert receipt.status == "steered" and receipt.result is None
        assert receipt.steered_into_run_id == original.result.run_id
        assert original.result.output == "Revised forecast."
        parts = await db.scalar(
            select(Message.parts).where(
                Message.run_id == original.result.run_id, Message.role == "assistant"
            )
        )
        assert parts and [part["type"] for part in parts] == ["tool", "steer", "text"]
        assert parts[1]["text"] == correction.prompt
    else:
        assert receipt.status == "queued"
        assert await run_next_job(sessions, pool="agent")
        async with sessions() as reader:
            completed = await ApiRunService(reader).get(webhook_ctx, receipt.id)
        assert completed.status == "completed" and completed.result is not None
        assert completed.result.run_id != original.result.run_id
        assert (original.result.output, completed.result.output) == (
            "Original forecast.",
            "Revised forecast.",
        )
    assert not await run_next_job(sessions, pool="agent")
    assert len(seen) == 2
    assert not any(correction.prompt in words for words in seen[0])
    assert sum(words.count(correction.prompt) for words in seen[1]) == 1
