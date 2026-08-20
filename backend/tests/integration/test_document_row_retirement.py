"""Which tracking rows a new attempt at a file retires, asked of a real Postgres.

#996. A file that failed to parse on one sync and succeeded on the next left
*both* rows: `complete_ingestion`'s retirement matches on `vector_document_id`
and a failed parse writes none, so the succeeding run had nothing to name. Every
repeated failure added another permanent row, and each one counted toward the
collection's `document_count`.

The obvious fix is the trap, which is why these are here rather than in the unit
suite: retiring "the previous row for this file" by **filename** deletes the
other file's row when a bucket holds `a/readme.md` beside `b/readme.md`. That is
the collision #990 removed on the vector side, reached from the other direction,
and only a real `DELETE ... WHERE` answers whether the predicate keeps them
apart.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.repositories import rag_document_repo

pytestmark = pytest.mark.anyio

COLLECTION = "org_handbook"


async def _row(
    db: AsyncSession,
    *,
    filename: str,
    source_path: str | None,
    vector_document_id: str | None,
    status: DocumentStatus = DocumentStatus.ERROR,
) -> RAGDocument:
    doc = RAGDocument(
        id=uuid.uuid4(),
        collection_name=COLLECTION,
        filename=filename,
        filesize=4,
        filetype="md",
        storage_path="",
        source_path=source_path,
        status=status,
        vector_document_id=vector_document_id,
        chunk_count=0,
        ingestion_config={},
    )
    db.add(doc)
    await db.flush()
    return doc


async def _surviving(db: AsyncSession) -> set[str]:
    result = await db.execute(
        select(RAGDocument.filename, RAGDocument.source_path).where(
            RAGDocument.collection_name == COLLECTION
        )
    )
    return {f"{name}@{path}" for name, path in result.all()}


class TestWhatANewAttemptRetires:
    async def test_a_failed_attempt_at_the_same_file_goes(self, db: AsyncSession):
        await _row(
            db,
            filename="readme.md",
            source_path="s3://bucket/a/readme.md",
            vector_document_id=None,
        )

        discarded = await rag_document_repo.discard_failed(
            db, collection_name=COLLECTION, source_path="s3://bucket/a/readme.md"
        )

        assert discarded == 1
        assert await _surviving(db) == set()

    async def test_another_key_of_the_same_basename_stays(self, db: AsyncSession):
        """The trap. Matching by `filename` would take this row out, and a first
        sync of a bucket holding both files could then never keep both."""
        await _row(
            db,
            filename="readme.md",
            source_path="s3://bucket/a/readme.md",
            vector_document_id=None,
        )
        await _row(
            db,
            filename="readme.md",
            source_path="s3://bucket/b/readme.md",
            vector_document_id=None,
        )

        discarded = await rag_document_repo.discard_failed(
            db, collection_name=COLLECTION, source_path="s3://bucket/a/readme.md"
        )

        assert discarded == 1
        assert await _surviving(db) == {"readme.md@s3://bucket/b/readme.md"}

    async def test_a_row_that_points_at_vectors_stays(self, db: AsyncSession):
        """It describes a document the store still holds, and the replacement
        that supersedes it has not been written yet - this runs *before* an
        ingest that may fail. `complete_ingestion` retires that one, after."""
        await _row(
            db,
            filename="readme.md",
            source_path="s3://bucket/a/readme.md",
            vector_document_id="vector-doc-1",
            status=DocumentStatus.DONE,
        )

        discarded = await rag_document_repo.discard_failed(
            db, collection_name=COLLECTION, source_path="s3://bucket/a/readme.md"
        )

        assert discarded == 0
        assert await _surviving(db) == {"readme.md@s3://bucket/a/readme.md"}

    async def test_an_attempt_still_running_stays(self, db: AsyncSession):
        """The race the predicate used to have. Two overlapping ingestions of one
        source - two manual triggers, nothing serialising them - and the second
        deleted the first's live `PROCESSING` row. The first then finished,
        replaced the vectors, and found no row to complete: one row pointing at
        deleted vectors, and the new vectors tracked by nothing."""
        await _row(
            db,
            filename="readme.md",
            source_path="s3://bucket/a/readme.md",
            vector_document_id=None,
            status=DocumentStatus.PROCESSING,
        )

        discarded = await rag_document_repo.discard_failed(
            db, collection_name=COLLECTION, source_path="s3://bucket/a/readme.md"
        )

        assert discarded == 0
        assert await _surviving(db) == {"readme.md@s3://bucket/a/readme.md"}

    async def test_a_row_with_no_address_stays(self, db: AsyncSession):
        """Written before the column existed. Its address is unknown, not equal to
        whatever is being ingested now, and a `NULL` matches no comparison - which
        is the behaviour wanted rather than one to work around."""
        await _row(db, filename="readme.md", source_path=None, vector_document_id=None)

        discarded = await rag_document_repo.discard_failed(
            db, collection_name=COLLECTION, source_path="s3://bucket/a/readme.md"
        )

        assert discarded == 0
        assert await _surviving(db) == {"readme.md@None"}

    async def test_another_collections_row_stays(self, db: AsyncSession):
        """Two organizations can hold the same object in collections of their own,
        and one sync must not reach into the other's rows."""
        theirs = RAGDocument(
            id=uuid.uuid4(),
            collection_name="someone_elses",
            filename="readme.md",
            filesize=4,
            filetype="md",
            storage_path="",
            source_path="s3://bucket/a/readme.md",
            status=DocumentStatus.ERROR,
            chunk_count=0,
            ingestion_config={},
        )
        db.add(theirs)
        await db.flush()

        discarded = await rag_document_repo.discard_failed(
            db, collection_name=COLLECTION, source_path="s3://bucket/a/readme.md"
        )

        assert discarded == 0
        remaining = await db.execute(
            select(RAGDocument.id).where(RAGDocument.collection_name == "someone_elses")
        )
        assert remaining.scalar_one() == theirs.id

    async def test_every_failed_attempt_goes_at_once(self, db: AsyncSession):
        """Rows accumulated one per failed sync, so a file failing nightly for a
        week left seven before the run that finally parsed it."""
        for _ in range(3):
            await _row(
                db,
                filename="readme.md",
                source_path="s3://bucket/a/readme.md",
                vector_document_id=None,
            )

        discarded = await rag_document_repo.discard_failed(
            db, collection_name=COLLECTION, source_path="s3://bucket/a/readme.md"
        )

        assert discarded == 3
        assert await _surviving(db) == set()
