"""History checkpoints advance monotonically and remain fenced by refusals."""

from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ephemeral_media import dump_messages
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation_repo
from app.services.conversation import ConversationService

pytestmark = pytest.mark.anyio


async def test_an_older_answer_cannot_replace_a_newer_checkpoint(db: AsyncSession) -> None:
    person = User(
        id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True
    )
    db.add(person)
    await db.flush()
    organization = Organization(
        id=uuid4(), name="History", slug=uuid4().hex, created_by_user_id=person.id
    )
    db.add(organization)
    await db.flush()
    conversation = Conversation(id=uuid4(), user_id=person.id, organization_id=organization.id)
    db.add(conversation)
    await db.flush()
    first = await conversation_repo.create_message(
        db, conversation_id=conversation.id, role="assistant", content="First"
    )
    second = await conversation_repo.create_message(
        db, conversation_id=conversation.id, role="assistant", content="Second"
    )
    service = ConversationService(db)
    newer = dump_messages([ModelRequest(parts=[UserPromptPart("Newer evidence")])])
    older = dump_messages([ModelRequest(parts=[UserPromptPart("Older evidence")])])
    await service.keep_summary(
        conversation.id, newer, expected_revision=0, through_message_id=str(second.id)
    )
    await service.keep_summary(
        conversation.id, older, expected_revision=0, through_message_id=str(first.id)
    )
    await db.refresh(conversation)
    assert conversation.summary_ordinal == second.ordinal
    assert conversation.summary_messages == newer
