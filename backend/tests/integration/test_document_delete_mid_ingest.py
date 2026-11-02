"""A document deleted while its ingest is still running leaves no chunks behind (#2565).

The delete purges by the row's `vector_document_id`, which stays `NULL` until the
ingest settles. Two things close that on Postgres: the delete takes the id from
its own `DELETE ... RETURNING`, so a settlement that committed first is seen, and
a settlement that finds the row gone queues the removal of the chunks it has just
written, as a job in its own transaction.
The write's `FOR KEY SHARE` hold on the row (`hold_for_vector_write`) is what
orders a delete that arrives mid-write after the chunk commit.
"""

import asyncio
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.background import drain, start_deferred
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.session import get_worker_db_context
from app.repositories import background_job as job_repo
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import IngestionResult, IngestionStatus
from app.services.rag.vectorstore import PgVectorStore
from app.services.rag_document import RAGDocumentService
from app.worker.jobs import DISCARD_VECTOR_DOCUMENT
from app.worker.tasks import rag_tasks, teardown_tasks
from tests.integration.test_deletion_reconciliation import (
    _kb_document,
    _org,
    _org_collection,
    _parsed,
    _store_embedding_in_3d,
    _user,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _chunks_of(s, table: str, document_id: str) -> int:
    return (
        await s.execute(
            text(f"SELECT count(*) FROM {table} WHERE parent_doc_id = :doc"),  # noqa: S608
            {"doc": document_id},
        )
    ).scalar_one()


class _Upload:
    """A base holding one settled neighbour, and a document whose ingest is open."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.factory = async_sessionmaker(engine, expire_on_commit=False)
        self.store: PgVectorStore = _store_embedding_in_3d(engine)
        self.collection = f"midingest{uuid.uuid4().hex[:12]}"
        self.table = self.store._table(self.collection)
        self.neighbour = _parsed("neighbour")

    async def open(self) -> None:
        async with self.factory() as s:
            owner = _user()
            s.add(owner)
            await s.flush()
            org = await _org(s, owner)
            base = _org_collection(org.id, self.collection)
            s.add(base)
            await s.flush()
            row = _kb_document(self.collection, base.id, org.id, "")
            row.status = DocumentStatus.PROCESSING
            row.vector_document_id = None
            s.add(row)
            await s.commit()
        self.base: KnowledgeBase = base
        self.row_id = row.id
        self.ingester = IngestionService(
            MagicMock(process_file=AsyncMock(return_value=_parsed("doomed"))),
            self.store,
            scope=base.vector_scope,
        )
        # Creates the table, and is what a purge reaching too far would take.
        await self.store.insert_document(self.collection, self.neighbour, base.vector_scope)

    async def ingest(self) -> IngestionResult:
        result = await self.ingester.ingest_file(
            Path("doomed.md"), self.collection, replace=False, rag_document_id=self.row_id
        )
        assert result.status is IngestionStatus.DONE
        assert result.document_id is not None
        return result

    async def delete(self, s) -> None:
        await RAGDocumentService(s).delete_document(str(self.row_id), self.ingester)
        await s.commit()
        start_deferred(s)

    async def settle(self, result: IngestionResult) -> None:
        """Settle as the sync does, then run what that queued, as a worker would."""
        await rag_tasks._settle_document_row(
            str(self.row_id), result, ingester=self.ingester, collection_name=self.collection
        )
        async with get_worker_db_context() as db:
            while job := await job_repo.claim(
                db, pool="system", worker_id="test", lease=timedelta(minutes=5)
            ):
                assert job.kind == DISCARD_VECTOR_DOCUMENT.kind
                await teardown_tasks.discard_vector_document(
                    DISCARD_VECTOR_DOCUMENT.load(job.payload)
                )
                await job_repo.complete(db, job.id, fence=job.attempts)

    async def remaining(self, result: IngestionResult) -> tuple[int, int]:
        assert result.document_id is not None
        async with self.factory() as s:
            return (
                await _chunks_of(s, self.table, result.document_id),
                await _chunks_of(s, self.table, self.neighbour.id),
            )

    async def close(self) -> None:
        async with self.factory() as s:
            await s.execute(text(f"DROP TABLE IF EXISTS {self.table}"))
            await s.commit()


@pytest.fixture
async def upload(engine: AsyncEngine):
    opened = _Upload(engine)
    await opened.open()
    try:
        yield opened
    finally:
        await opened.close()


async def test_a_delete_between_the_write_and_the_settlement_leaves_no_chunks(
    upload: _Upload,
) -> None:
    """The chunks are committed and the row has no vector id yet: the delete
    purges nothing, so the settlement that finds the row gone removes them."""
    result = await upload.ingest()

    async with upload.factory() as s:
        await upload.delete(s)
    await drain()
    await upload.settle(result)

    assert await upload.remaining(result) == (0, 1)
    async with upload.factory() as s:
        assert await s.get(RAGDocument, upload.row_id) is None


async def _until_a_statement_waits_on_a_lock(factory) -> None:
    for _ in range(250):
        async with factory() as s:
            waiting = await s.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("The delete never waited for the write")


async def test_a_delete_during_the_write_waits_for_it_and_leaves_no_chunks(
    upload: _Upload, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write holds its row `FOR KEY SHARE` from before its insert to its
    commit. A delete arriving in that window waits on it, then removes a row
    still without a vector id - the order where a guard before the write cannot
    help, and the settlement has to clean up."""
    deleting: list[asyncio.Task[None]] = []
    ensure = upload.store._ensure_collection

    async def ensure_with_a_delete_queued(name: str) -> None:
        await ensure(name)

        # The row hold is taken by now; the delete starts and queues behind it.
        async def delete() -> None:
            async with upload.factory() as s:
                await upload.delete(s)

        deleting.append(asyncio.create_task(delete()))
        await _until_a_statement_waits_on_a_lock(upload.factory)

    monkeypatch.setattr(upload.store, "_ensure_collection", ensure_with_a_delete_queued)
    result = await upload.ingest()
    await asyncio.wait_for(deleting[0], timeout=10)
    await drain()
    await upload.settle(result)

    assert await upload.remaining(result) == (0, 1)


async def test_a_delete_that_read_the_row_before_the_settlement_purges_what_it_settled(
    upload: _Upload,
) -> None:
    """The route loads the row before the service deletes it, and the settlement
    can commit in between. The settlement found its row, so it removes nothing;
    the delete must purge by the vector id the row holds when it is deleted, not
    the `NULL` it read."""
    result = await upload.ingest()

    async with upload.factory() as s:
        # What `access.writable_document` does in the route, in the same session.
        loaded = await RAGDocumentService(s).get_document(str(upload.row_id))
        assert loaded.vector_document_id is None
        await upload.settle(result)
        await upload.delete(s)
    await drain()

    assert await upload.remaining(result) == (0, 1)


async def test_a_settlement_after_its_table_was_dropped_removes_nothing_quietly(
    upload: _Upload, caplog: pytest.LogCaptureFixture
) -> None:
    """A last base deleted mid-ingest drops the table with every chunk in it, so the
    settlement that finds the row gone has nothing left to remove - and says so at
    INFO rather than as a failed delete."""
    import logging

    result = await upload.ingest()
    async with upload.factory() as s:
        await s.execute(text(f"DELETE FROM rag_documents WHERE id = '{upload.row_id}'"))  # noqa: S608
        await s.execute(text(f"DROP TABLE {upload.table}"))
        await s.commit()

    with caplog.at_level(logging.INFO):
        await upload.settle(result)

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
