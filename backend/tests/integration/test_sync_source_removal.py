"""Which rows a sync may delete as no longer listed, asked of a real Postgres (#987).

`list_settled_for_source` is what a sync reads before deleting what its source
stopped listing, so its `WHERE` is the whole of what keeps that delete inside one
source's own documents. It asks by the source's id: two sources can read the same
repository and branch into one collection with different include patterns, and
an address prefix would have each delete what only the other lists. A
`PROCESSING` row belongs to an attempt still running and is not a candidate.

The per-source run lock is here too, because what it promises - a second session
cannot take it, and closing the first releases it - is Postgres's behaviour and
nothing a mock can show.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.locks import LockScope, try_hold_subject_on_connection
from app.db.models.organization import Organization
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.repositories import rag_document_repo
from app.repositories import sync_source as sync_source_repo

pytestmark = pytest.mark.anyio

COLLECTION = "handbook"
ROOT = "git://git.test/acme/hand_book@main/"


async def _org(db: AsyncSession) -> Organization:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Org",
        slug=f"org-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _source(db: AsyncSession, organization: Organization) -> SyncSource:
    source = SyncSource(
        id=uuid.uuid4(),
        organization_id=organization.id,
        name="Docs",
        connector_type="git",
        config={},
        collection_name=COLLECTION,
    )
    db.add(source)
    await db.flush()
    return source


async def _row(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    source_path: str,
    sync_source_id: uuid.UUID | None,
    status: DocumentStatus = DocumentStatus.DONE,
    collection_name: str = COLLECTION,
) -> RAGDocument:
    doc = RAGDocument(
        id=uuid.uuid4(),
        collection_name=collection_name,
        filename=source_path.rsplit("/", 1)[-1],
        filesize=4,
        filetype="md",
        storage_path="",
        source_path=source_path,
        status=status,
        vector_document_id="vec",
        chunk_count=1,
        ingestion_config={},
        organization_id=organization_id,
        sync_source_id=sync_source_id,
    )
    db.add(doc)
    await db.flush()
    return doc


class TestWhatASyncMayDeleteAsUnlisted:
    async def test_only_this_sources_settled_rows_in_its_collection(self, db: AsyncSession) -> None:
        org = await _org(db)
        mine, other = await _source(db, org), await _source(db, org)
        done = await _row(
            db, organization_id=org.id, source_path=f"{ROOT}docs/a.md", sync_source_id=mine.id
        )
        failed = await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}docs/b.md",
            sync_source_id=mine.id,
            status=DocumentStatus.ERROR,
        )
        # Its own, and still running.
        await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}docs/c.md",
            sync_source_id=mine.id,
            status=DocumentStatus.PROCESSING,
        )
        # The same address, read by another source into the same collection.
        await _row(
            db, organization_id=org.id, source_path=f"{ROOT}docs/a.md", sync_source_id=other.id
        )
        # An upload with no source, and this source's row in another collection.
        await _row(db, organization_id=org.id, source_path=f"{ROOT}docs/d.md", sync_source_id=None)
        await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}docs/e.md",
            sync_source_id=mine.id,
            collection_name="elsewhere",
        )

        rows = await rag_document_repo.list_settled_for_source(
            db, sync_source_id=mine.id, collection_name=COLLECTION
        )

        assert {row.id for row in rows} == {done.id, failed.id}

    async def test_deleting_the_source_keeps_what_it_ingested(self, db: AsyncSession) -> None:
        org = await _org(db)
        source = await _source(db, org)
        doc = await _row(
            db, organization_id=org.id, source_path=f"{ROOT}a.md", sync_source_id=source.id
        )

        await sync_source_repo.delete(db, source.id)
        await db.refresh(doc)

        assert doc.sync_source_id is None


class TestOneRunOfASourceAtATime:
    async def test_a_second_connection_cannot_take_the_lock_until_the_first_closes(
        self, engine: AsyncEngine
    ) -> None:
        """Held across the commit the check makes - the lock is the connection's,
        not the transaction's - and gone with the connection, with nothing to unlock."""
        subject = uuid.uuid4()
        scope = LockScope.SYNC_SOURCE_RUN
        async with engine.connect() as first:
            assert await try_hold_subject_on_connection(first, scope, subject)
            async with engine.connect() as second:
                assert not await try_hold_subject_on_connection(second, scope, subject)
                assert await try_hold_subject_on_connection(second, scope, uuid.uuid4())
            await first.invalidate()
        async with engine.connect() as third:
            assert await try_hold_subject_on_connection(third, scope, subject)

    async def test_a_worker_connection_holds_the_lock_for_its_whole_block(
        self, engine: AsyncEngine
    ) -> None:
        """What `_exclusive_source_run` stands on: through `get_worker_connection`,
        a NullPool engine of its own on the suite's database, the lock survives
        until the block exits."""
        from app.db.session import get_worker_connection

        subject = uuid.uuid4()
        scope = LockScope.SYNC_SOURCE_RUN
        async with get_worker_connection() as held:
            assert await try_hold_subject_on_connection(held, scope, subject)
            async with engine.connect() as other:
                assert not await try_hold_subject_on_connection(other, scope, subject)
        async with engine.connect() as after:
            assert await try_hold_subject_on_connection(after, scope, subject)


class TestTheStoredSyncState:
    async def test_a_state_is_kept_by_a_run_that_records_none(self, db: AsyncSession) -> None:
        """A failed run passes no state, and must not erase the last clean one."""
        org = await _org(db)
        source = SyncSource(
            id=uuid.uuid4(), organization_id=org.id, name="Docs", connector_type="git", config={}
        )
        db.add(source)
        await db.flush()
        state = {"version": "abc123", "fingerprint": "f" * 64}
        await sync_source_repo.update_sync_status(
            db, source.id, last_sync_at=datetime.now(UTC), last_sync_status="done", sync_state=state
        )
        await sync_source_repo.update_sync_status(
            db, source.id, last_sync_at=datetime.now(UTC), last_sync_status="error", last_error="x"
        )
        await db.refresh(source)

        assert source.sync_state == state
