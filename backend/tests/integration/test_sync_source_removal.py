"""Which rows a sync may delete as no longer listed, asked of a real Postgres (#987).

`list_settled_under` is what a sync reads before deleting what its source stopped
listing, so its `WHERE` is the whole of what keeps that delete inside one
source's own documents. Three ways it could reach further, each only a real
query answers:

- a collection name is not unique across organizations (#1684);
- `_` and `%` are `LIKE` wildcards, and a repository called `a_b` is a prefix
  pattern that also matches `aXb` unless it is escaped;
- a `PROCESSING` row belongs to an attempt still running.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _row(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    source_path: str,
    status: DocumentStatus = DocumentStatus.DONE,
) -> RAGDocument:
    doc = RAGDocument(
        id=uuid.uuid4(),
        collection_name=COLLECTION,
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
    )
    db.add(doc)
    await db.flush()
    return doc


class TestWhatASyncMayDeleteAsUnlisted:
    async def test_only_this_organizations_settled_rows_under_the_root(
        self, db: AsyncSession
    ) -> None:
        mine, theirs = await _org(db), await _org(db)
        done = await _row(db, organization_id=mine.id, source_path=f"{ROOT}docs/a.md")
        failed = await _row(
            db, organization_id=mine.id, source_path=f"{ROOT}docs/b.md", status=DocumentStatus.ERROR
        )
        await _row(
            db,
            organization_id=mine.id,
            source_path=f"{ROOT}docs/c.md",
            status=DocumentStatus.PROCESSING,
        )
        await _row(db, organization_id=theirs.id, source_path=f"{ROOT}docs/a.md")
        await _row(
            db, organization_id=mine.id, source_path="git://git.test/acme/handXbook@main/a.md"
        )
        await _row(
            db, organization_id=mine.id, source_path="git://git.test/acme/hand_book@dev/a.md"
        )

        rows = await rag_document_repo.list_settled_under(
            db,
            collection_name=COLLECTION,
            knowledge_base_id=None,
            organization_id=mine.id,
            source_root=ROOT,
        )

        assert {row.id for row in rows} == {done.id, failed.id}


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
