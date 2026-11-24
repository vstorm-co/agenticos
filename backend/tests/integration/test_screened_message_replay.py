"""A real stored transcript never undoes an earlier input replacement (#2655)."""

from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.guardrails import GuardrailsConfig, build_guardrails
from app.agents.capabilities.guardrails._capability import input_screen
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation as repo
from app.services.conversation import ConversationService
from app.services.message_history import REFUSED_TURN
from app.services.screened_replay import screened_copy

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("private", ["sk-ant-api03-ABCDEFGHIJKLMNOPQR", "alice@example.com"])
async def test_two_turns_and_a_guardrail_disabled_later_replay_only_the_screened_copy(
    db: AsyncSession, private: str
):
    owner = User(
        id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True
    )
    db.add(owner)
    await db.flush()
    org = Organization(id=uuid4(), name="Replay", slug=uuid4().hex, created_by_user_id=owner.id)
    db.add(org)
    await db.flush()
    conversation = Conversation(
        id=uuid4(), user_id=owner.id, organization_id=org.id, title="Replay"
    )
    db.add(conversation)
    await db.flush()
    config = GuardrailsConfig(redact_secrets_in=True, redact_pii_in=True)
    capability = build_guardrails(config)
    assert capability is not None
    seen: list[bytes] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(ModelMessagesTypeAdapter.dump_json(messages))
        return ModelResponse(parts=[TextPart("Done")])

    agent: Agent = Agent(model=FunctionModel(answer), capabilities=[capability])
    raw = f"Remember {private}"
    attachment = f"\nAttachment briefing: {private}"
    await agent.run(raw + attachment)
    assert private.encode() not in seen[-1]
    copy = screened_copy(raw, attachment, input_screen(config))
    assert copy is not None and private not in copy
    row = await repo.create_message(
        db,
        conversation_id=conversation.id,
        role="user",
        content=raw,
        attachment_context=attachment,
        model_content=copy,
    )
    await repo.create_message(db, conversation_id=conversation.id, role="assistant", content="Done")
    history = await ConversationService(db).model_history(conversation.id, limit=50)
    await agent.run("What did I say?", message_history=history)
    assert private.encode() not in seen[-1]
    unguarded: Agent = Agent(model=FunctionModel(answer))
    await unguarded.run("Repeat it", message_history=history)
    assert private.encode() not in seen[-1]
    assert row.content == raw and row.attachment_context == attachment
    # A blocked turn takes precedence even over a stale or malformed replacement.
    row.guardrail_refused = True
    row.model_content = private
    await db.flush()
    blocked = await ConversationService(db).model_history(conversation.id, limit=50)
    encoded = ModelMessagesTypeAdapter.dump_json(blocked).decode()
    assert private not in encoded and REFUSED_TURN in encoded
