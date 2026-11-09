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


@pytest.mark.security
async def test_the_shared_list_holds_only_the_named_organizations(db: AsyncSession) -> None:
    """A reader in two organizations sees, in each, only that one's shares."""
    from app.db.models.organization import OrganizationMember

    owner, reader = await _user(db), await _user(db)
    conversations = []
    for name in ("Acme", "Globex"):
        organization = Organization(
            name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
        )
        db.add(organization)
        await db.flush()
        db.add(OrganizationMember(organization_id=organization.id, user_id=reader.id))
        conversation = Conversation(
            user_id=owner.id, organization_id=organization.id, title=f"{name} plan"
        )
        db.add(conversation)
        await db.flush()
        await conversation_share_repo.create(
            db, conversation_id=conversation.id, shared_by=owner.id, shared_with=reader.id
        )
        conversations.append(conversation)
    acme, globex = conversations

    listed = await conversation_share_repo.get_conversations_shared_with_user(
        db, reader.id, organization_id=acme.organization_id
    )

    assert [c.id for c in listed] == [acme.id]
    assert (
        await conversation_share_repo.count_conversations_shared_with_user(
            db, reader.id, organization_id=globex.organization_id
        )
        == 1
    )


@pytest.mark.security
async def test_a_revoked_share_hides_its_notification_before_read_or_delivery(
    db: AsyncSession,
) -> None:
    from app.core.permissions import AuthContext
    from app.db.models.notification import Notification, NotificationEventType
    from app.db.models.organization import OrganizationMember
    from app.services.notification_center import NotificationCenterService

    owner, reader = await _user(db), await _user(db)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=reader.id))
    conversation = Conversation(
        user_id=owner.id, organization_id=organization.id, title="Private plan"
    )
    db.add(conversation)
    await db.flush()
    share = await conversation_share_repo.create(
        db, conversation_id=conversation.id, shared_by=owner.id, shared_with=reader.id
    )
    notification = Notification(
        recipient_user_id=reader.id,
        organization_id=organization.id,
        event_type=NotificationEventType.RESOURCE_SHARED.value,
        summary="Private plan was shared",
        occurrence_id="share",
        render_context={"resource_kind": "conversation", "resource_id": str(conversation.id)},
    )
    ctx = AuthContext(user_id=reader.id, organization_id=organization.id, role="member")
    service = NotificationCenterService(db)
    assert (await service.gate_for(ctx, notification)).visible
    await db.delete(share)
    await db.flush()
    assert not (await service.gate_for(ctx, notification)).visible


@pytest.mark.parametrize("resource_id", [None, "", "not-an-id"])
async def test_an_unresolvable_conversation_notice_is_hidden(
    db: AsyncSession, resource_id: str | None
) -> None:
    from app.core.permissions import AuthContext
    from app.db.models.notification import Notification, NotificationEventType
    from app.services.notification_center import NotificationCenterService

    row = Notification(
        event_type=NotificationEventType.RESOURCE_SHARED.value,
        render_context={"resource_kind": "conversation", "resource_id": resource_id},
    )
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="member")
    assert not (await NotificationCenterService(db).gate_for(ctx, row)).visible


@pytest.mark.parametrize("missing", ["user", "organization"])
async def test_a_conversation_notice_requires_a_user_and_organization(
    db: AsyncSession, missing: str
) -> None:
    from app.core.permissions import AuthContext
    from app.db.models.notification import Notification, NotificationEventType
    from app.services.notification_center import NotificationCenterService

    row = Notification(
        event_type=NotificationEventType.RESOURCE_SHARED.value,
        render_context={"resource_kind": "conversation", "resource_id": str(uuid.uuid4())},
    )
    ctx = AuthContext(
        user_id=None if missing == "user" else uuid.uuid4(),
        organization_id=None if missing == "organization" else uuid.uuid4(),
        role="member",
    )
    assert not (await NotificationCenterService(db).gate_for(ctx, row)).visible


async def test_other_group_share_notices_retain_their_existing_policy(db: AsyncSession) -> None:
    from app.core.permissions import AuthContext
    from app.db.models.notification import Notification, NotificationEventType
    from app.services.notification_center import NotificationCenterService

    row = Notification(
        event_type=NotificationEventType.RESOURCE_SHARED.value,
        render_context={"resource_kind": "agent", "resource_id": str(uuid.uuid4())},
    )
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="member")
    assert (await NotificationCenterService(db).gate_for(ctx, row)).visible


async def test_legacy_project_shares_do_not_appear_as_individual_shared_chats(
    db: AsyncSession,
) -> None:
    from app.db.models.organization import OrganizationMember
    from app.db.models.project import Project

    owner, reader = await _user(db), await _user(db)
    org = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=reader.id))
    project = Project(organization_id=org.id, owner_user_id=owner.id, name="Restricted project")
    db.add(project)
    await db.flush()
    conversation = Conversation(
        user_id=owner.id,
        organization_id=org.id,
        project_id=project.id,
        title="Legacy shared project chat",
    )
    db.add(conversation)
    await db.flush()
    await conversation_share_repo.create(
        db, conversation_id=conversation.id, shared_by=owner.id, shared_with=reader.id
    )
    assert (
        await conversation_share_repo.get_conversations_shared_with_user(
            db, reader.id, organization_id=org.id
        )
        == []
    )
    assert (
        await conversation_share_repo.count_conversations_shared_with_user(
            db, reader.id, organization_id=org.id
        )
        == 0
    )
