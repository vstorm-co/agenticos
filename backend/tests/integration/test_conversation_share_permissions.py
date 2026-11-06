"""What a conversation share lets its reader do, read back for the shared-with-me list."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation_share as conversation_share_repo

pytestmark = pytest.mark.anyio


async def _user(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


@pytest.mark.security
async def test_each_share_reads_back_with_what_it_allows_its_own_reader(db: AsyncSession) -> None:
    owner, reader, other = await _user(db), await _user(db), await _user(db)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    read_only, writable, not_theirs = (
        Conversation(user_id=owner.id, organization_id=organization.id, title=title)
        for title in ("Read", "Write", "Other's")
    )
    db.add_all([read_only, writable, not_theirs])
    await db.flush()
    for conversation, shared_with, permission in (
        (read_only, reader, "view"),
        (writable, reader, "edit"),
        (not_theirs, other, "edit"),
    ):
        await conversation_share_repo.create(
            db,
            conversation_id=conversation.id,
            shared_by=owner.id,
            shared_with=shared_with.id,
            permission=permission,
        )

    permissions = await conversation_share_repo.share_permissions(
        db,
        user_id=reader.id,
        conversation_ids=[read_only.id, writable.id, not_theirs.id],
    )

    assert permissions == {read_only.id: "view", writable.id: "edit"}


@pytest.mark.security
async def test_a_changed_share_reads_back_with_its_new_permission(db: AsyncSession) -> None:
    owner, reader = await _user(db), await _user(db)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    conversation = Conversation(user_id=owner.id, organization_id=organization.id, title="Plan")
    db.add(conversation)
    await db.flush()
    share = await conversation_share_repo.create(
        db, conversation_id=conversation.id, shared_by=owner.id, shared_with=reader.id
    )

    await conversation_share_repo.set_permission(db, share=share, permission="edit")

    assert await conversation_share_repo.share_permissions(
        db, user_id=reader.id, conversation_ids=[conversation.id]
    ) == {conversation.id: "edit"}
