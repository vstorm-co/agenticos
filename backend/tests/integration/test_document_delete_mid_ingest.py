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
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.agents.capabilities.budget import SpendLedger, record_ambient_cost
from app.core.background import drain, start_deferred
from app.db.models.ingestion_spend import IngestionSpend
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.session import get_worker_db_context
from app.repositories import background_job as job_repo
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import IngestionResult, IngestionStatus
from app.services.rag.vectorstore import PgVectorStore
from app.services.rag_document import RAGDocumentService
from app.worker.jobs import DISCARD_VECTOR_DOCUMENT, IngestDocument
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


def _errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


async def _run_queued() -> list[str]:
    """Run the jobs the settlement queued, as a worker would; return their kinds."""
    kinds: list[str] = []
    async with get_worker_db_context() as db:
        while job := await job_repo.claim(
            db, pool="system", worker_id="test", lease=timedelta(minutes=5)
        ):
            kinds.append(job.kind)
            assert job.kind == DISCARD_VECTOR_DOCUMENT.kind
            await teardown_tasks.discard_vector_document(DISCARD_VECTOR_DOCUMENT.load(job.payload))
            await job_repo.complete(db, job.id, fence=job.attempts)
    return kinds


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
        await _run_queued()

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
    raise AssertionError("No statement ever waited on a lock")


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

    # The delete discovered the newly settled id. Its cleanup survives the API
    # process exiting after commit, rather than relying on its deferred tasks.
    assert await upload.remaining(result) == (1, 1)
    assert await _run_queued() == [DISCARD_VECTOR_DOCUMENT.kind]

    assert await upload.remaining(result) == (0, 1)


async def test_a_settlement_after_its_table_was_dropped_removes_nothing_quietly(
    upload: _Upload, caplog: pytest.LogCaptureFixture
) -> None:
    """A last base deleted mid-ingest drops the table with every chunk in it, so the
    settlement that finds the row gone has nothing left to remove - and says so at
    INFO rather than as a failed delete."""
    result = await upload.ingest()
    async with upload.factory() as s:
        await s.execute(text(f"DELETE FROM rag_documents WHERE id = '{upload.row_id}'"))  # noqa: S608
        await s.execute(text(f"DROP TABLE {upload.table}"))
        await s.commit()

    with caplog.at_level(logging.INFO):
        await upload.settle(result)

    assert _errors(caplog) == []


class _Worker:
    """`ingest_document` run whole against the upload, its spend booked for real.

    Nothing on the job's own path is mocked but the parse and the pipeline's
    construction: the spend is recorded by `_record_embedding_spend` into
    `ingestion_spend`, whose foreign key to the row is what a document deleted
    mid-ingest broke - after the write, so the settlement that would have
    removed the chunks never ran (#2565).
    """

    def __init__(self, upload: _Upload, monkeypatch: pytest.MonkeyPatch) -> None:
        self.upload = upload
        self.before_write: Callable[[], Awaitable[None]] | None = None
        self.after_write: Callable[[], Awaitable[None]] | None = None
        self.queued: list[str] = []
        ingester = upload.ingester

        async def ingest_file(*args: object, **kwargs: Any) -> IngestionResult:
            # What the embedder books inside the job's metering window.
            record_ambient_cost("text-embedding-3-small", Decimal("0.0002"))
            if self.before_write is not None:
                await self.before_write()
            result = await IngestionService.ingest_file(ingester, *args, **kwargs)
            if self.after_write is not None:
                await self.after_write()
            return result

        @asynccontextmanager
        async def ingestion_service(**_: object) -> AsyncIterator[object]:
            yield SimpleNamespace(ingest_file=ingest_file, scope=ingester.scope)

        monkeypatch.setattr(rag_tasks, "_ingestion_service", ingestion_service)
        monkeypatch.setattr(
            rag_tasks.IngestionConfigService,
            "build_processor",
            AsyncMock(return_value=MagicMock()),
        )

    async def delete(self) -> None:
        async with self.upload.factory() as s:
            await self.upload.delete(s)
        await drain()

    async def run(self) -> dict[str, Any]:
        """The job, then whatever it queued, as the worker would run them."""
        outcome = await rag_tasks.ingest_document(
            IngestDocument(
                rag_document_id=self.upload.row_id,
                collection_name=self.upload.collection,
                filepath="queued/doomed.md",
                source_path="doomed.md",
                replace=False,
                attempt=1,
            )
        )
        self.queued = await _run_queued()
        return outcome

    async def chunks(self) -> int:
        async with self.upload.factory() as s:
            return (
                await s.execute(
                    text(
                        f"SELECT count(*) FROM {self.upload.table} "  # noqa: S608
                        "WHERE parent_doc_id <> :neighbour"
                    ),
                    {"neighbour": self.upload.neighbour.id},
                )
            ).scalar_one()

    async def spend(self) -> list[tuple[uuid.UUID | None, str]]:
        async with self.upload.factory() as s:
            rows = await s.execute(
                select(IngestionSpend.rag_document_id, IngestionSpend.model).where(
                    IngestionSpend.organization_id == self.upload.base.organization_id
                )
            )
            return [(row_id, model) for row_id, model in rows.all()]


@pytest.fixture
def worker(upload: _Upload, monkeypatch: pytest.MonkeyPatch) -> _Worker:
    return _Worker(upload, monkeypatch)


async def test_an_upload_deleted_after_its_chunk_commit_ends_with_its_spend_kept(
    worker: _Worker, caplog: pytest.LogCaptureFixture
) -> None:
    """Deleted between the chunk commit and the settlement, with spend booked:
    the spend is kept against no document, the chunks are removed by the job the
    settlement queues, and the job ends without a retry or a traceback."""
    worker.after_write = worker.delete

    with caplog.at_level(logging.INFO):
        outcome = await worker.run()

    assert outcome == {"status": "deleted", "filename": "doomed.md"}
    assert worker.queued == [DISCARD_VECTOR_DOCUMENT.kind]
    assert await worker.chunks() == 0
    assert await worker.spend() == [(None, "text-embedding-3-small")]
    assert _errors(caplog) == []


async def test_an_upload_deleted_during_its_chunk_write_ends_with_its_spend_kept(
    worker: _Worker, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The delete arrives while the write holds the row, and waits for its commit:
    the order the manual run forced by holding the vector table locked."""
    deleting: list[asyncio.Task[None]] = []
    store = worker.upload.store
    ensure = store._ensure_collection

    async def ensure_with_a_delete_queued(name: str) -> None:
        await ensure(name)
        deleting.append(asyncio.create_task(worker.delete()))
        await _until_a_statement_waits_on_a_lock(worker.upload.factory)

    monkeypatch.setattr(store, "_ensure_collection", ensure_with_a_delete_queued)

    async def delete_finished() -> None:
        await asyncio.wait_for(deleting[0], timeout=10)

    worker.after_write = delete_finished

    with caplog.at_level(logging.INFO):
        outcome = await worker.run()

    assert outcome == {"status": "deleted", "filename": "doomed.md"}
    assert worker.queued == [DISCARD_VECTOR_DOCUMENT.kind]
    assert await worker.chunks() == 0
    assert await worker.spend() == [(None, "text-embedding-3-small")]
    assert _errors(caplog) == []


async def test_an_upload_deleted_before_its_chunk_write_ends_with_its_spend_kept(
    worker: _Worker, caplog: pytest.LogCaptureFixture
) -> None:
    """Deleted while it embedded: the write is refused, nothing is written, and the
    spend the embedding booked is still kept."""
    worker.before_write = worker.delete

    with caplog.at_level(logging.INFO):
        outcome = await worker.run()

    assert outcome["status"] == "refused"
    assert worker.queued == []
    assert await worker.chunks() == 0
    assert await worker.spend() == [(None, "text-embedding-3-small")]
    assert _errors(caplog) == []


async def test_spend_on_a_document_still_there_is_kept_against_it(
    worker: _Worker,
) -> None:
    outcome = await worker.run()

    assert outcome["status"] == "done"
    assert await worker.spend() == [(worker.upload.row_id, "text-embedding-3-small")]


async def test_spend_recorded_while_its_organization_purges_the_document_keeps_it(
    worker: _Worker, caplog: pytest.LogCaptureFixture
) -> None:
    """The purge holds its organization `FOR UPDATE`, then deletes the documents.

    The spend waits behind the organization, as the purge orders the two, and then
    finds the document gone: it is kept against none. Locking the document first
    and the organization at the insert deadlocked the two (#2565).
    """
    upload = worker.upload
    organization_id = upload.base.organization_id
    ledger = SpendLedger(organization_id=organization_id)
    ledger.record_cost("text-embedding-3-small", Decimal("0.0002"))

    with caplog.at_level(logging.INFO):
        async with upload.factory() as purge:
            await purge.execute(
                select(Organization.id).where(Organization.id == organization_id).with_for_update()
            )
            recording = asyncio.create_task(
                rag_tasks._record_embedding_spend(
                    ledger, organization_id=organization_id, rag_document_id=upload.row_id
                )
            )
            await _until_a_statement_waits_on_a_lock(upload.factory)
            await purge.execute(delete(RAGDocument).where(RAGDocument.id == upload.row_id))
            await purge.commit()
        await asyncio.wait_for(recording, timeout=10)

    assert await worker.spend() == [(None, "text-embedding-3-small")]
    assert _errors(caplog) == []
