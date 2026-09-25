"""Which rows a sync may delete as no longer listed, asked of a real Postgres (#987).

`get_settled_for_sync_source` is what a sync reads before deleting what its
source stopped listing, so its `WHERE` is the whole of what keeps that delete
inside one source's own documents. It asks by the source's claims: two sources
can read the same repository and branch into one collection with different
include patterns, and an address prefix would have each delete what only the
other lists. A `PROCESSING` row is not a candidate: it is
`get_stale_for_sync_source`'s, which the run holding the source's lock settles
first. A document both sources claim is removed by neither alone (#1879).

The per-source run lock is here too, because what it promises - a second session
cannot take it, and closing the first releases it - is Postgres's behaviour and
nothing a mock can show.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.locks import LockScope, try_hold_subject_on_connection
from app.db.models.organization import Organization
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.rag_document_claim import RAGDocumentClaim
from app.db.models.sync_source import SyncSource
from app.db.models.user import User
from app.repositories import rag_document_repo
from app.repositories import sync_source as sync_source_repo
from app.services.rag_document import RAGDocumentService

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


async def _source(
    db: AsyncSession, organization: Organization, *, collection_name: str = COLLECTION
) -> SyncSource:
    source = SyncSource(
        id=uuid.uuid4(),
        organization_id=organization.id,
        name="Docs",
        connector_type="git",
        config={},
        collection_name=collection_name,
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
    vector_document_id: str = "vec",
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
        vector_document_id=vector_document_id,
        chunk_count=1,
        ingestion_config={},
        organization_id=organization_id,
    )
    db.add(doc)
    await db.flush()
    if sync_source_id is not None:
        db.add(RAGDocumentClaim(rag_document_id=doc.id, sync_source_id=sync_source_id))
        await db.flush()
    return doc


async def _claimants(db: AsyncSession, doc: RAGDocument) -> set[uuid.UUID]:
    result = await db.execute(
        select(RAGDocumentClaim.sync_source_id).where(RAGDocumentClaim.rag_document_id == doc.id)
    )
    return set(result.scalars().all())


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

        rows = await rag_document_repo.get_settled_for_sync_source(
            db, sync_source_id=mine.id, collection_name=COLLECTION
        )

        assert {row.id for row in rows} == {done.id, failed.id}

    async def test_the_stale_rows_are_this_sources_processing_ones(self, db: AsyncSession) -> None:
        org = await _org(db)
        mine, other = await _source(db, org), await _source(db, org)
        stale = await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}a.md",
            sync_source_id=mine.id,
            status=DocumentStatus.PROCESSING,
        )
        await _row(db, organization_id=org.id, source_path=f"{ROOT}b.md", sync_source_id=mine.id)
        await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}a.md",
            sync_source_id=other.id,
            status=DocumentStatus.PROCESSING,
        )
        await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}c.md",
            sync_source_id=mine.id,
            status=DocumentStatus.PROCESSING,
            collection_name="elsewhere",
        )

        rows = await rag_document_repo.get_stale_for_sync_source(
            db, sync_source_id=mine.id, collection_name=COLLECTION
        )

        assert [row.id for row in rows] == [stale.id]

    async def test_a_stored_document_is_tracked_by_any_row_of_the_collection(
        self, db: AsyncSession
    ) -> None:
        """Another source's row, or an upload's, tracks a document as much as this source's."""
        org = await _org(db)
        await _row(db, organization_id=org.id, source_path=f"{ROOT}a.md", sync_source_id=None)
        await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}b.md",
            sync_source_id=None,
            collection_name="elsewhere",
        )

        tracked = await rag_document_repo.get_tracked_vector_ids(
            db, collection_name=COLLECTION, vector_document_ids={"vec", "orphan"}
        )

        assert tracked == {"vec"}
        assert (
            await rag_document_repo.get_tracked_vector_ids(
                db, collection_name=COLLECTION, vector_document_ids=set()
            )
            == set()
        )

    async def test_deleting_the_source_keeps_what_it_ingested(self, db: AsyncSession) -> None:
        org = await _org(db)
        source = await _source(db, org)
        doc = await _row(
            db, organization_id=org.id, source_path=f"{ROOT}a.md", sync_source_id=source.id
        )

        await sync_source_repo.delete(db, source.id)

        assert await rag_document_repo.get_by_id(db, doc.id) is not None
        assert await _claimants(db, doc) == set()


class TestTwoSourcesClaimingOneDocument:
    """A document stays while any source feeding its collection still lists it (#1879)."""

    async def test_another_sources_claim_keeps_it_and_this_ones_does_not(
        self, db: AsyncSession
    ) -> None:
        org = await _org(db)
        mine, other = await _source(db, org), await _source(db, org)
        shared = await _row(
            db, organization_id=org.id, source_path=f"{ROOT}a.md", sync_source_id=mine.id
        )
        db.add(RAGDocumentClaim(rag_document_id=shared.id, sync_source_id=other.id))
        only_mine = await _row(
            db, organization_id=org.id, source_path=f"{ROOT}b.md", sync_source_id=mine.id
        )
        await db.flush()

        assert await rag_document_repo.is_claimed_by_another_source(
            db, shared.id, sync_source_id=mine.id
        )
        assert not await rag_document_repo.is_claimed_by_another_source(
            db, only_mine.id, sync_source_id=mine.id
        )

    async def test_a_source_repointed_elsewhere_no_longer_keeps_it(self, db: AsyncSession) -> None:
        """Its claim outlives the repoint, but it lists nothing here any more,
        and would otherwise keep the document for good."""
        org = await _org(db)
        mine = await _source(db, org)
        moved = await _source(db, org, collection_name="elsewhere")
        doc = await _row(
            db, organization_id=org.id, source_path=f"{ROOT}a.md", sync_source_id=mine.id
        )
        db.add(RAGDocumentClaim(rag_document_id=doc.id, sync_source_id=moved.id))
        await db.flush()

        assert not await rag_document_repo.is_claimed_by_another_source(
            db, doc.id, sync_source_id=mine.id
        )

    async def test_releasing_a_shared_document_drops_only_this_claim(
        self, db: AsyncSession
    ) -> None:
        org = await _org(db)
        mine, other = await _source(db, org), await _source(db, org)
        shared = await _row(
            db, organization_id=org.id, source_path=f"{ROOT}a.md", sync_source_id=mine.id
        )
        db.add(RAGDocumentClaim(rag_document_id=shared.id, sync_source_id=other.id))
        only_mine = await _row(
            db, organization_id=org.id, source_path=f"{ROOT}b.md", sync_source_id=mine.id
        )
        await db.flush()
        documents = RAGDocumentService(db)

        assert await documents.release_if_shared(str(shared.id), sync_source_id=mine.id)
        # The last claimant keeps its claim, so a vector delete that fails
        # leaves the document this source's to retry.
        assert not await documents.release_if_shared(str(only_mine.id), sync_source_id=mine.id)
        assert await _claimants(db, shared) == {other.id}
        assert await _claimants(db, only_mine) == {mine.id}

    async def test_an_unchanged_document_is_claimed_by_its_address_and_vector_id(
        self, db: AsyncSession
    ) -> None:
        """Only the row the sync compared against: not a stale row at the same
        address, not the same vector id at another, not an unsettled row."""
        org = await _org(db)
        mine, other = await _source(db, org), await _source(db, org)
        compared = await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}a.md",
            sync_source_id=other.id,
            vector_document_id="vec-a",
        )
        stale = await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}a.md",
            sync_source_id=other.id,
            vector_document_id="vec-old",
        )
        elsewhere = await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}b.md",
            sync_source_id=None,
            vector_document_id="vec-a",
        )
        running = await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}c.md",
            sync_source_id=None,
            status=DocumentStatus.PROCESSING,
            vector_document_id="vec-c",
        )
        pairs = {(f"{ROOT}a.md", "vec-a"), (f"{ROOT}c.md", "vec-c")}
        documents = RAGDocumentService(db)

        await documents.claim_unchanged(
            sync_source_id=mine.id, collection_name=COLLECTION, documents=pairs
        )
        # Claiming again is a no-op, not a conflict.
        await documents.claim_unchanged(
            sync_source_id=mine.id, collection_name=COLLECTION, documents=pairs
        )
        await documents.claim_unchanged(
            sync_source_id=mine.id, collection_name=COLLECTION, documents=set()
        )

        assert await _claimants(db, compared) == {other.id, mine.id}
        assert await _claimants(db, stale) == {other.id}
        assert await _claimants(db, elsewhere) == set()
        assert await _claimants(db, running) == set()

    async def test_a_replacement_at_the_same_address_takes_over_the_claims(
        self, db: AsyncSession
    ) -> None:
        """A second source re-ingesting a page retires the first's row, and must
        not retire the first source's claim with it. A row the store matched at
        another address - by name or by content - keeps its claims to itself."""
        org = await _org(db)
        first, second = await _source(db, org), await _source(db, org)
        copier = await _source(db, org)
        same_address = await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}a.md",
            sync_source_id=first.id,
            vector_document_id="vec-old",
        )
        other_address = await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}copy-of-a.md",
            sync_source_id=copier.id,
            vector_document_id="vec-old",
        )
        replacement = await _row(
            db,
            organization_id=org.id,
            source_path=f"{ROOT}a.md",
            sync_source_id=second.id,
            status=DocumentStatus.PROCESSING,
            vector_document_id="",
        )

        await RAGDocumentService(db).complete_ingestion(
            str(replacement.id),
            vector_document_id="vec-new",
            chunk_count=1,
            replaced_document_id="vec-old",
            attempt=1,
        )

        assert await rag_document_repo.get_by_id(db, same_address.id) is None
        assert await rag_document_repo.get_by_id(db, other_address.id) is None
        assert await _claimants(db, replacement) == {first.id, second.id}


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
