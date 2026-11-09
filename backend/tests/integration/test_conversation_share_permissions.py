"""What a conversation share lets its reader do, read back for the shared-with-me list."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation_share as conversation_share_repo

pytestmark = [pytest.mark.anyio, pytest.mark.security]


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


async def test_active_shares_are_filtered_before_pagination_and_counting(db: AsyncSession) -> None:
    from app.db.models.organization import OrganizationMember

    owner, reader = await _user(db), await _user(db)
    org = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=reader.id))
    active = Conversation(user_id=owner.id, organization_id=org.id, title="Older active share")
    db.add(active)
    await db.flush()
    await conversation_share_repo.create(
        db, conversation_id=active.id, shared_by=owner.id, shared_with=reader.id
    )
    for index in range(3):
        archived = Conversation(
            user_id=owner.id, organization_id=org.id, title=f"Archived {index}", is_archived=True
        )
        db.add(archived)
        await db.flush()
        await conversation_share_repo.create(
            db, conversation_id=archived.id, shared_by=owner.id, shared_with=reader.id
        )
    listed = await conversation_share_repo.get_conversations_shared_with_user(
        db, reader.id, organization_id=org.id, limit=1, include_archived=False
    )
    assert [row.id for row in listed] == [active.id]
    assert (
        await conversation_share_repo.count_conversations_shared_with_user(
            db, reader.id, organization_id=org.id, include_archived=False
        )
        == 1
    )
    assert (
        await conversation_share_repo.count_conversations_shared_with_user(
            db, reader.id, organization_id=org.id
        )
        == 4
    )


async def test_shared_pagination_uses_activity_dates_and_a_stable_tie_breaker(
    db: AsyncSession,
) -> None:
    from datetime import UTC, datetime

    from app.db.models.organization import OrganizationMember

    owner, reader = await _user(db), await _user(db)
    org = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=reader.id))
    older = datetime(2026, 10, 1, tzinfo=UTC)
    recent = datetime(2026, 11, 1, tzinfo=UTC)
    idle = Conversation(
        user_id=owner.id, organization_id=org.id, title="Never updated", created_at=older
    )
    active = Conversation(
        user_id=owner.id,
        organization_id=org.id,
        title="Recently active",
        created_at=older,
        updated_at=recent,
    )
    newest = Conversation(
        user_id=owner.id, organization_id=org.id, title="Newly shared", created_at=recent
    )
    db.add_all([idle, active, newest])
    await db.flush()
    for conversation in (idle, active, newest):
        await conversation_share_repo.create(
            db, conversation_id=conversation.id, shared_by=owner.id, shared_with=reader.id
        )
    expected = sorted([active.id, newest.id], reverse=True)
    first = await conversation_share_repo.get_conversations_shared_with_user(
        db, reader.id, organization_id=org.id, include_archived=False, limit=1
    )
    second = await conversation_share_repo.get_conversations_shared_with_user(
        db, reader.id, organization_id=org.id, include_archived=False, skip=1, limit=1
    )
    assert [row.id for row in first + second] == expected


async def test_shared_sidebar_rows_do_not_load_conversation_working_state(db: AsyncSession) -> None:
    from sqlalchemy import inspect
    from sqlalchemy.exc import InvalidRequestError

    from app.db.models.organization import OrganizationMember

    owner, reader = await _user(db), await _user(db)
    org = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=reader.id))
    conversation = Conversation(
        user_id=owner.id,
        organization_id=org.id,
        title="Shared plan",
        plan_items=[{"content": "Private working state"}],
        summary_messages=[{"text": "Large summary"}],
    )
    db.add(conversation)
    await db.flush()
    await conversation_share_repo.create(
        db, conversation_id=conversation.id, shared_by=owner.id, shared_with=reader.id
    )
    reader_id, org_id = reader.id, org.id
    db.expunge_all()
    rows = await conversation_share_repo.get_conversations_shared_with_user(
        db, reader_id, organization_id=org_id, include_archived=False
    )
    assert len(rows) == 1
    assert {"summary_messages", "plan_items", "reminder_state"}.issubset(inspect(rows[0]).unloaded)
    for field in ("summary_messages", "plan_items"):
        with pytest.raises(InvalidRequestError):
            getattr(rows[0], field)


async def test_shared_favourites_are_ranked_before_the_page_limit_for_the_reader(
    db: AsyncSession,
) -> None:
    from datetime import UTC, datetime

    from app.db.models.organization import OrganizationMember
    from app.repositories import conversation as conversation_repo

    owner, reader, other = await _user(db), await _user(db), await _user(db)
    org = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(org)
    await db.flush()
    db.add_all(
        [OrganizationMember(organization_id=org.id, user_id=user.id) for user in (reader, other)]
    )
    old = Conversation(
        user_id=owner.id,
        organization_id=org.id,
        title="Starred",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    new = Conversation(user_id=owner.id, organization_id=org.id, title="Newer")
    db.add_all([old, new])
    await db.flush()
    for user in (reader, other):
        for row in (old, new):
            await conversation_share_repo.create(
                db, conversation_id=row.id, shared_by=owner.id, shared_with=user.id
            )
    await conversation_repo.set_favourite(
        db, user_id=reader.id, conversation_id=old.id, favourite=True
    )
    assert [
        row.id
        for row in await conversation_share_repo.get_conversations_shared_with_user(
            db, reader.id, limit=1
        )
    ] == [old.id]
    assert [
        row.id
        for row in await conversation_share_repo.get_conversations_shared_with_user(
            db, other.id, limit=1
        )
    ] == [new.id]
    assert await conversation_share_repo.count_conversations_shared_with_user(db, reader.id) == 2


async def test_share_notice_batch_uses_constant_queries_for_many_active_and_revoked_shares(
    db: AsyncSession,
) -> None:
    from sqlalchemy import event

    from app.core.permissions import AuthContext
    from app.db.models.notification import Notification, NotificationEventType
    from app.db.models.organization import OrganizationMember
    from app.services.notification_center import NotificationCenterService

    owner, reader = await _user(db), await _user(db)
    organization = Organization(
        name="Acme", slug=f"batch-{uuid.uuid4().hex}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=reader.id))
    notices = []
    visible = set()
    for index in range(40):
        row = Conversation(
            user_id=None if index % 10 == 1 else owner.id,
            organization_id=organization.id,
            title=f"Shared {index}",
        )
        db.add(row)
        await db.flush()
        if index % 2 == 0:
            await conversation_share_repo.create(
                db, conversation_id=row.id, shared_by=owner.id, shared_with=reader.id
            )
            visible.add(row.id)
        notices.append(
            Notification(
                event_type=NotificationEventType.RESOURCE_SHARED.value,
                render_context={"resource_kind": "conversation", "resource_id": str(row.id)},
            )
        )
    queries = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)

    assert db.bind is not None
    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        cache = await NotificationCenterService(db)._build_gate_cache(
            AuthContext(user_id=reader.id, organization_id=organization.id, role="member"), notices
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(queries) <= 8, queries
    assert sum(cache.conversation_visible_by_id.values()) == 20
    assert {key for key, allowed in cache.conversation_visible_by_id.items() if allowed} == visible
