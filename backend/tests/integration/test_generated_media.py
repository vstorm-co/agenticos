"""Generated media rows against a real database: the link, the sums and the deletes (#2310).

A mock cannot say whether a scalar subquery links a conversation from another
tenant, whether `SET NULL` keeps a row when its thread goes, or whether a sum is
scoped - and each of those is the difference between a quota and a leak.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.generated_media import GeneratedMedia
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import generated_media_repo, retention_repo

pytestmark = pytest.mark.anyio

_LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
"""An `unlinked_cutoff` no row is older than, so a test reads by `cutoff` alone."""


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db) -> Organization:
    founder = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _conversation(db, organization: Organization) -> Conversation:
    owner = await _user(db)
    conversation = Conversation(
        id=uuid.uuid4(), user_id=owner.id, organization_id=organization.id, title="Clips"
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _media(
    db, organization: Organization, *, conversation_id: uuid.UUID | None = None, size: int = 10
) -> GeneratedMedia:
    leaf = f"{uuid.uuid4().hex[:12]}_video.mp4"
    return await generated_media_repo.create(
        db,
        organization_id=organization.id,
        conversation_id=conversation_id,
        filename=leaf,
        storage_path=f"generated_{organization.id}/{leaf}",
        size_bytes=size,
    )


async def test_a_file_is_linked_to_its_own_organizations_conversation(db):
    organization = await _org(db)
    conversation = await _conversation(db, organization)

    row = await _media(db, organization, conversation_id=conversation.id)

    assert row.conversation_id == conversation.id
    assert row.created_at is not None
    assert "video.mp4" in repr(row)


@pytest.mark.parametrize("whose", ["another organization's", "a missing", "no"])
async def test_a_conversation_that_is_not_this_organizations_is_not_linked(db, whose: str):
    """A preview has no saved thread, and an id from another tenant is never one
    to hang this tenant's file on - either way the row is kept, unlinked."""
    organization, other = await _org(db), await _org(db)
    conversation_id = {
        "another organization's": (await _conversation(db, other)).id,
        "a missing": uuid.uuid4(),
        "no": None,
    }[whose]

    row = await _media(db, organization, conversation_id=conversation_id)

    assert row.conversation_id is None


async def test_the_quota_sums_this_organizations_files_alone(db):
    organization, other = await _org(db), await _org(db)
    thread, theirs = await _conversation(db, organization), await _conversation(db, other)
    await _media(db, organization, conversation_id=thread.id, size=3 * 1024**3)
    await _media(db, organization, conversation_id=thread.id, size=7)
    await _media(db, other, conversation_id=theirs.id, size=1000)

    assert await generated_media_repo.bytes_used(db, organization_id=organization.id) == (
        3 * 1024**3 + 7
    )
    assert await generated_media_repo.bytes_used(db, organization_id=(await _org(db)).id) == 0


async def test_the_quota_counts_files_made_with_no_conversation(db):
    """A preview's, a `/btw` aside's or an API run's file has no conversation, and
    still counts: left out, repeating any of them generated past the quota for
    free. The sweep removes it after its short lifetime instead (#2310)."""
    organization = await _org(db)
    thread = await _conversation(db, organization)
    await _media(db, organization, conversation_id=thread.id, size=7)
    await _media(db, organization, size=1000)

    assert await generated_media_repo.bytes_used(db, organization_id=organization.id) == 1007


async def test_an_accounts_conversations_give_up_their_media_in_every_organization(db):
    first, second = await _org(db), await _org(db)
    person = await _user(db)
    mine = [
        Conversation(id=uuid.uuid4(), user_id=person.id, organization_id=org.id, title="Mine")
        for org in (first, second)
    ]
    db.add_all(mine)
    await db.flush()
    ours = await _conversation(db, first)
    gone = [await _media(db, org, conversation_id=c.id) for org, c in zip((first, second), mine)]
    kept = await _media(db, first, conversation_id=ours.id)
    unlinked = await _media(db, first)

    paths = await generated_media_repo.delete_in_conversations_of_user(db, user_id=person.id)

    assert sorted(paths) == sorted(row.storage_path for row in gone)
    remaining = set((await db.execute(select(GeneratedMedia.id))).scalars().all())
    assert remaining == {kept.id, unlinked.id}


async def test_forgetting_conversations_reaches_only_theirs_in_this_tenant(db):
    organization, other = await _org(db), await _org(db)
    gone, kept = await _conversation(db, organization), await _conversation(db, organization)
    in_gone = await _media(db, organization, conversation_id=gone.id)
    in_kept = await _media(db, organization, conversation_id=kept.id)

    assert await generated_media_repo.paths_in_conversations(
        db, organization_id=organization.id, conversation_ids=[gone.id]
    ) == [in_gone.storage_path]
    assert (
        await generated_media_repo.paths_in_conversations(
            db, organization_id=other.id, conversation_ids=[gone.id]
        )
        == []
    )
    assert (
        await generated_media_repo.delete_in_conversations(
            db, organization_id=other.id, conversation_ids=[gone.id]
        )
        == 0
    )
    assert (
        await generated_media_repo.delete_in_conversations(
            db, organization_id=organization.id, conversation_ids=[gone.id]
        )
        == 1
    )
    remaining = (await db.execute(select(GeneratedMedia.id))).scalars().all()
    assert remaining == [in_kept.id]


async def test_an_empty_list_of_anything_reads_and_deletes_nothing(db):
    organization = await _org(db)
    await _media(db, organization)

    assert (
        await generated_media_repo.paths_in_conversations(
            db, organization_id=organization.id, conversation_ids=[]
        )
        == []
    )
    assert (
        await generated_media_repo.delete_in_conversations(
            db, organization_id=organization.id, conversation_ids=[]
        )
        == 0
    )
    assert (
        await generated_media_repo.delete_by_storage_paths(
            db, organization_id=organization.id, storage_paths=[]
        )
        == 0
    )
    assert await generated_media_repo.delete_by_ids(db, ids=[]) == 0
    assert len((await db.execute(select(GeneratedMedia.id))).scalars().all()) == 1


async def test_rows_are_deleted_by_path_in_this_tenant_only(db):
    organization, other = await _org(db), await _org(db)
    row = await _media(db, organization)

    assert (
        await generated_media_repo.delete_by_storage_paths(
            db, organization_id=other.id, storage_paths=[row.storage_path]
        )
        == 0
    )
    assert (
        await generated_media_repo.delete_by_storage_paths(
            db, organization_id=organization.id, storage_paths=[row.storage_path, "user/a.pdf"]
        )
        == 1
    )


async def test_the_sweep_reads_the_oldest_first_across_organizations(db):
    first, second = await _org(db), await _org(db)
    older = await _media(db, first)
    newer = await _media(db, second)
    now = datetime.now(UTC)
    await db.execute(
        GeneratedMedia.__table__.update()
        .where(GeneratedMedia.id == older.id)
        .values(created_at=now - timedelta(days=100))
    )
    await db.execute(
        GeneratedMedia.__table__.update()
        .where(GeneratedMedia.id == newer.id)
        .values(created_at=now - timedelta(days=50))
    )

    assert [
        row.id
        for row in await generated_media_repo.expired(
            db, unlinked_cutoff=_LONG_AGO, cutoff=now - timedelta(days=30), limit=10
        )
    ] == [older.id, newer.id]
    assert [
        row.id
        for row in await generated_media_repo.expired(
            db, unlinked_cutoff=_LONG_AGO, cutoff=now - timedelta(days=30), limit=1
        )
    ] == [older.id]
    assert (
        await generated_media_repo.expired(
            db, unlinked_cutoff=_LONG_AGO, cutoff=now - timedelta(days=200), limit=10
        )
        == []
    )
    assert [
        row.id
        for row in await generated_media_repo.expired(
            db,
            unlinked_cutoff=_LONG_AGO,
            cutoff=now - timedelta(days=30),
            limit=10,
            after=(now - timedelta(days=100), older.id),
        )
    ] == [newer.id]
    assert await generated_media_repo.delete_by_ids(db, ids=[older.id]) == 1


async def test_a_file_with_no_conversation_expires_on_its_own_shorter_bound(db):
    """With retention off (`cutoff=None`) a file made with no conversation still
    expires at `unlinked_cutoff`; one made in a conversation does not (#2310)."""
    organization = await _org(db)
    thread = await _conversation(db, organization)
    unlinked = await _media(db, organization)
    linked = await _media(db, organization, conversation_id=thread.id)
    fresh = await _media(db, organization)
    now = datetime.now(UTC)
    await db.execute(
        GeneratedMedia.__table__.update()
        .where(GeneratedMedia.id.in_([unlinked.id, linked.id]))
        .values(created_at=now - timedelta(days=10))
    )
    week = now - timedelta(days=7)

    expired = await generated_media_repo.expired(db, cutoff=None, unlinked_cutoff=week, limit=10)
    assert [row.id for row in expired] == [unlinked.id]
    assert fresh.id not in [row.id for row in expired]
    both = await generated_media_repo.expired(
        db, cutoff=now - timedelta(days=9), unlinked_cutoff=week, limit=10
    )
    assert {row.id for row in both} == {unlinked.id, linked.id}


async def test_the_sweep_reads_past_a_row_with_its_own_timestamp_by_id(db):
    """Rows created in one transaction share `created_at`; the id breaks the tie,
    so a batch boundary inside them neither repeats nor skips one."""
    organization = await _org(db)
    rows = [await _media(db, organization) for _ in range(3)]
    stamp = datetime.now(UTC) - timedelta(days=100)
    await db.execute(GeneratedMedia.__table__.update().values(created_at=stamp))
    ordered = sorted(row.id for row in rows)
    cutoff = datetime.now(UTC) - timedelta(days=30)

    first = await generated_media_repo.expired(
        db, cutoff=cutoff, unlinked_cutoff=_LONG_AGO, limit=2
    )
    rest = await generated_media_repo.expired(
        db, cutoff=cutoff, unlinked_cutoff=_LONG_AGO, limit=2, after=(stamp, first[-1].id)
    )

    assert [row.id for row in first + rest] == ordered


async def test_a_deleted_conversation_leaves_its_rows_for_the_sweep(db):
    """`SET NULL`: a path that deletes a thread without unlinking its media must
    not delete the only record of the bytes."""
    organization = await _org(db)
    conversation = await _conversation(db, organization)
    row = await _media(db, organization, conversation_id=conversation.id)

    await db.execute(delete(Conversation).where(Conversation.id == conversation.id))
    await db.refresh(row)

    assert row.conversation_id is None


async def test_a_deleted_organization_takes_its_rows(db):
    organization = await _org(db)
    await _media(db, organization)

    await db.execute(delete(Organization).where(Organization.id == organization.id))

    assert (await db.execute(select(GeneratedMedia.id))).scalars().all() == []


async def test_a_conversation_purged_by_retention_names_its_generated_files(db):
    """The retention sweep unlinks what the thread's agents generated with its
    attachments; the rows would not cascade, so the paths have to be read here."""
    organization = await _org(db)
    conversation = await _conversation(db, organization)
    message = Message(id=uuid.uuid4(), conversation_id=conversation.id, role="user", content="x")
    db.add(message)
    await db.flush()
    db.add(
        ChatFile(
            id=uuid.uuid4(),
            user_id=conversation.user_id,
            message_id=message.id,
            filename="a.pdf",
            mime_type="application/pdf",
            size=1,
            storage_path="user/a.pdf",
            file_type="document",
        )
    )
    row = await _media(db, organization, conversation_id=conversation.id)
    await db.execute(
        Conversation.__table__.update()
        .where(Conversation.id == conversation.id)
        .values(updated_at=datetime.now(UTC) - timedelta(days=100))
    )

    paths = await retention_repo.stored_paths_for_expiring_conversations(
        db,
        organization_id=organization.id,
        cutoff=datetime.now(UTC) - timedelta(days=30),
        limit=10,
    )

    assert sorted(paths) == sorted(["user/a.pdf", row.storage_path])
