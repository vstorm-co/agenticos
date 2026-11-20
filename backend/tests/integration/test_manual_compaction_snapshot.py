"""PostgreSQL fences for manually compacted conversation snapshots."""

import uuid
from copy import deepcopy

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.schemas.conversation import HistoryProvenance
from app.services.conversation import ConversationService

_PROVENANCE = HistoryProvenance(agent_id=uuid.uuid4(), configuration_digest="0" * 64)

pytestmark = pytest.mark.anyio


async def _owner(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _conversation(db: AsyncSession, owner: User) -> Conversation:
    organization = Organization(
        id=uuid.uuid4(),
        name="Manual compaction",
        slug=f"manual-compaction-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(organization)
    await db.flush()

    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=organization.id,
        title="Snapshot fence",
        summary_messages=[{"role": "user", "content": "Prior cache"}],
        summary_ordinal=0,
        guardrail_revision=4,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _message(db: AsyncSession, conversation: Conversation, content: str) -> Message:
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="user",
        content=content,
    )
    db.add(message)
    await db.flush()
    return message


async def test_an_unchanged_snapshot_replaces_the_prior_summary(db: AsyncSession) -> None:
    owner = await _owner(db)
    conversation = await _conversation(db, owner)
    message = await _message(db, conversation, "Captured history")
    snapshot = [{"role": "assistant", "content": "Compacted history"}]

    stored = await ConversationService(db).keep_summary_snapshot(
        conversation.id,
        snapshot,
        expected_revision=conversation.guardrail_revision,
        expected_ordinal=message.ordinal,
        provenance=_PROVENANCE,
    )
    await db.refresh(conversation)

    assert stored is True
    assert conversation.summary_messages == {
        "version": 1,
        "provenance": _PROVENANCE.model_dump(mode="json"),
        "messages": snapshot,
    }
    assert conversation.summary_ordinal == message.ordinal


async def test_a_newer_message_rejects_the_snapshot_and_preserves_the_prior_summary(
    db: AsyncSession,
) -> None:
    owner = await _owner(db)
    conversation = await _conversation(db, owner)
    snapshot_message = await _message(db, conversation, "Captured history")
    prior_summary = deepcopy(conversation.summary_messages)
    await _message(db, conversation, "Arrived after the snapshot")

    stored = await ConversationService(db).keep_summary_snapshot(
        conversation.id,
        [{"role": "assistant", "content": "Stale compacted history"}],
        expected_revision=conversation.guardrail_revision,
        expected_ordinal=snapshot_message.ordinal,
        provenance=_PROVENANCE,
    )
    await db.refresh(conversation)

    assert stored is False
    assert conversation.summary_messages == prior_summary
    assert conversation.summary_ordinal == 0


async def test_a_guardrail_revision_change_rejects_the_snapshot_and_preserves_the_prior_summary(
    db: AsyncSession,
) -> None:
    owner = await _owner(db)
    conversation = await _conversation(db, owner)
    message = await _message(db, conversation, "Captured history")
    prior_summary = deepcopy(conversation.summary_messages)
    expected_revision = conversation.guardrail_revision
    conversation.guardrail_revision += 1
    await db.flush()

    stored = await ConversationService(db).keep_summary_snapshot(
        conversation.id,
        [{"role": "assistant", "content": "Obsolete compacted history"}],
        expected_revision=expected_revision,
        expected_ordinal=message.ordinal,
        provenance=_PROVENANCE,
    )
    await db.refresh(conversation)

    assert stored is False
    assert conversation.summary_messages == prior_summary
    assert conversation.summary_ordinal == 0
