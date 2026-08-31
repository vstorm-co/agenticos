"""How many chunks a document produced reaches the row that reports it.

#147. `complete_ingestion` defaulted `chunk_count` to `0` and all four call
sites took the default, so every `rag_documents` row ever written claimed zero
chunks while the collection answered searches perfectly well - the knowledge
base cards showed an empty collection and the parsed-content view, which counts
the vector store live, showed the real number on the same screen.

The default is gone, which is what stops a fifth call site repeating it. These
pin the number to the path it travels: the pipeline counts, the result carries,
the worker records.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import background
from app.repositories import rag_document_repo
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import (
    Document,
    DocumentMetadata,
    DocumentPage,
    DocumentPageChunk,
    IngestionStatus,
)
from app.services.rag.vectorstore import BaseVectorStore
from app.services.rag_document import RAGDocumentService
from app.worker.tasks.rag_tasks import _run_ingestion

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_leftover_tasks():
    """A deferred unlink one test starts must not be drained by the next."""
    background._running.clear()
    yield
    background._running.clear()


def _deferring_db() -> MagicMock:
    """A session stand-in whose `info` is a real dict, so `spawn_after_commit`
    queues on it the way a live session's does."""
    db = MagicMock()
    db.info = {}
    return db


async def _run_deferred(db: MagicMock) -> None:
    """What `_managed_session` does the instant its commit returns."""
    background.start_deferred(db)
    await background.drain(timeout=5.0)


def _document(*, chunks: int) -> Document:
    document = Document(
        pages=[DocumentPage(page_num=1, content="body")],
        metadata=DocumentMetadata(filename="handbook.md", filesize=10, filetype="md"),
    )
    document.chunked_pages = [
        DocumentPageChunk(
            chunk_content=f"chunk {index}",
            chunk_num=index,
            page_num=1,
            content=f"chunk {index}",
        )
        for index in range(chunks)
    ]
    return document


def _service(processor: MagicMock) -> IngestionService:
    store = MagicMock(insert_document=AsyncMock(), delete_document=AsyncMock())
    store.find_existing_document = BaseVectorStore.find_existing_document.__get__(store)
    return IngestionService(processor=processor, vector_store=store)


class TestWhatThePipelineReports:
    async def test_a_successful_ingest_reports_the_chunks_it_stored(self):
        processor = MagicMock(process_file=AsyncMock(return_value=_document(chunks=7)))

        result = await _service(processor).ingest_file(
            filepath=Path("handbook.md"), collection_name="docs", replace=False
        )

        assert result.status is IngestionStatus.DONE
        assert result.chunk_count == 7

    async def test_a_failed_ingest_reports_no_chunks(self):
        """A parse that never produced a chunk must not leave a number behind
        for a document whose row is about to say `error`."""
        processor = MagicMock(process_file=AsyncMock(side_effect=ValueError("unreadable")))

        result = await _service(processor).ingest_file(
            filepath=Path("scan.pdf"), collection_name="docs", replace=False
        )

        assert result.status is IngestionStatus.ERROR
        assert result.chunk_count == 0


class TestSkippingADroppedCollection:
    """A collection deleted while a file parsed must not be resurrected by the
    index that follows (#1275)."""

    async def test_a_gone_collection_is_not_written(self):
        processor = MagicMock(process_file=AsyncMock(return_value=_document(chunks=3)))
        service = _service(processor)

        result = await service.ingest_file(
            filepath=Path("handbook.md"),
            collection_name="docs",
            replace=False,
            still_wanted=AsyncMock(return_value=False),
        )

        assert result.status is IngestionStatus.ERROR
        # The write is skipped, so `_ensure_collection` never recreates the table.
        service.store.insert_document.assert_not_awaited()

    async def test_a_live_collection_is_still_written(self):
        processor = MagicMock(process_file=AsyncMock(return_value=_document(chunks=3)))
        service = _service(processor)

        result = await service.ingest_file(
            filepath=Path("handbook.md"),
            collection_name="docs",
            replace=False,
            still_wanted=AsyncMock(return_value=True),
        )

        assert result.status is IngestionStatus.DONE
        service.store.insert_document.assert_awaited_once()


class TestWhatTheUploadPathRecords:
    async def test_the_worker_writes_the_chunk_count_it_was_given(self):
        document_id = str(uuid.uuid4())
        record = MagicMock(organization_id=uuid.uuid4(), ingestion_config={})
        documents = MagicMock(
            get_document=AsyncMock(return_value=record), complete_ingestion=AsyncMock()
        )

        @asynccontextmanager
        async def _worker_db():
            yield MagicMock()

        ingestion = MagicMock(
            ingest_file=AsyncMock(
                return_value=MagicMock(
                    status=IngestionStatus.DONE,
                    document_id="vector-doc",
                    chunk_count=42,
                    replaced_document_id=None,
                )
            ),
        )

        @asynccontextmanager
        async def _pipeline(**_kwargs: object) -> AsyncIterator[MagicMock]:
            yield ingestion

        with (
            patch("app.worker.tasks.rag_tasks.get_worker_db_context", _worker_db),
            patch("app.services.rag_document.RAGDocumentService", return_value=documents),
            patch("app.worker.tasks.rag_tasks.assert_organization_within_budget", new=AsyncMock()),
            patch("app.worker.tasks.rag_tasks._ingestion_service", new=_pipeline),
            patch("app.worker.tasks.rag_tasks._record_embedding_spend", new=AsyncMock()),
        ):
            await _run_ingestion(document_id, "docs", "queued/handbook.md", "handbook.md", False)

        documents.complete_ingestion.assert_awaited_once_with(
            document_id,
            vector_document_id="vector-doc",
            chunk_count=42,
            replaced_document_id=None,
        )

    @pytest.mark.parametrize("name", ["chunk_count", "replaced_document_id"])
    def test_recording_an_ingest_cannot_omit_what_it_must_report(self, name):
        """The signature is the guard. Four call sites took a `chunk_count=0`
        default and nothing anywhere failed, so the number is keyword-only and
        required - a fifth caller does not compile rather than reporting zero.
        `replaced_document_id` is the same trap: omitting it leaves the replaced
        document's row behind and the collection over-reports by its size.
        """
        parameter = inspect.signature(RAGDocumentService.complete_ingestion).parameters[name]

        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


class TestRetiringWhatAReplacementDeleted:
    """Every ingest path creates a fresh `rag_documents` row, the replacing one
    included, while the vector store keeps a single document. So the row that
    pointed at the deleted vectors has to go with them - otherwise
    `counts_by_collection` keeps summing its `chunk_count`, and a directory
    synced nightly reports a collection growing by its own size every night.
    """

    async def test_a_replacing_ingest_reports_which_document_it_deleted(self):
        processor = MagicMock(process_file=AsyncMock(return_value=_document(chunks=3)))
        service = _service(processor)
        service.store.get_documents = AsyncMock(
            return_value=[
                MagicMock(
                    document_id="old-vector-doc",
                    additional_info={"source_path": "handbook.md"},
                )
            ]
        )

        result = await service.ingest_file(
            filepath=Path("handbook.md"),
            collection_name="docs",
            replace=True,
            source_path="handbook.md",
        )

        assert result.replaced_document_id == "old-vector-doc"
        service.store.delete_document.assert_awaited_once_with("docs", "old-vector-doc")

    async def test_a_first_ingest_reports_nothing_replaced(self):
        processor = MagicMock(process_file=AsyncMock(return_value=_document(chunks=3)))
        service = _service(processor)
        service.store.get_documents = AsyncMock(return_value=[])

        result = await service.ingest_file(
            filepath=Path("handbook.md"), collection_name="docs", replace=True
        )

        assert result.replaced_document_id is None

    async def test_completing_a_replacement_deletes_the_row_it_superseded(self, monkeypatch):
        stale_id = uuid.uuid4()
        stale = MagicMock(id=stale_id, storage_path="rag/docs/handbook.md")
        current = MagicMock(id=uuid.uuid4(), collection_name="docs")
        deleted: list[uuid.UUID] = []
        storage = MagicMock(delete=AsyncMock())

        monkeypatch.setattr(rag_document_repo, "update_status", AsyncMock())
        monkeypatch.setattr(rag_document_repo, "get_superseded", AsyncMock(return_value=[stale]))
        monkeypatch.setattr(
            rag_document_repo,
            "delete",
            AsyncMock(side_effect=lambda _db, doc_id: deleted.append(doc_id)),
        )
        monkeypatch.setattr("app.services.file_storage.get_file_storage", lambda: storage)

        db = _deferring_db()
        service = RAGDocumentService(db)
        monkeypatch.setattr(service, "get_document", AsyncMock(return_value=current))
        await service.complete_ingestion(
            str(current.id),
            vector_document_id="new-vector-doc",
            chunk_count=9,
            replaced_document_id="old-vector-doc",
        )

        # The row goes in the transaction; the file is unlinked only once it commits.
        assert deleted == [stale_id]
        storage.delete.assert_not_awaited()
        await _run_deferred(db)
        storage.delete.assert_awaited_once_with("rag/docs/handbook.md")

    async def test_a_storage_backend_that_refuses_still_loses_the_row(self, monkeypatch):
        """The database must not go on describing vectors nobody holds because a
        file could not be unlinked - the deferred unlink swallows its failure.
        """
        stale = MagicMock(id=uuid.uuid4(), storage_path="rag/docs/handbook.md")
        deleted: list[uuid.UUID] = []

        monkeypatch.setattr(rag_document_repo, "update_status", AsyncMock())
        monkeypatch.setattr(rag_document_repo, "get_superseded", AsyncMock(return_value=[stale]))
        monkeypatch.setattr(
            rag_document_repo,
            "delete",
            AsyncMock(side_effect=lambda _db, doc_id: deleted.append(doc_id)),
        )
        monkeypatch.setattr(
            "app.services.file_storage.get_file_storage",
            lambda: MagicMock(delete=AsyncMock(side_effect=OSError("read-only volume"))),
        )

        db = _deferring_db()
        service = RAGDocumentService(db)
        monkeypatch.setattr(
            service,
            "get_document",
            AsyncMock(return_value=MagicMock(id=uuid.uuid4(), collection_name="docs")),
        )
        await service.complete_ingestion(
            "doc",
            vector_document_id="new-vector-doc",
            chunk_count=9,
            replaced_document_id="old-vector-doc",
        )
        await _run_deferred(db)

        assert deleted == [stale.id]

    async def test_a_row_with_no_stored_file_is_deleted_without_touching_storage(self, monkeypatch):
        """The sync path creates its tracking rows with no `storage_path` at all,
        and it is the path that accumulates them fastest.
        """
        stale = MagicMock(id=uuid.uuid4(), storage_path="")
        storage = MagicMock(delete=AsyncMock())
        deleted: list[uuid.UUID] = []

        monkeypatch.setattr(rag_document_repo, "update_status", AsyncMock())
        monkeypatch.setattr(rag_document_repo, "get_superseded", AsyncMock(return_value=[stale]))
        monkeypatch.setattr(
            rag_document_repo,
            "delete",
            AsyncMock(side_effect=lambda _db, doc_id: deleted.append(doc_id)),
        )
        monkeypatch.setattr("app.services.file_storage.get_file_storage", lambda: storage)

        db = _deferring_db()
        service = RAGDocumentService(db)
        monkeypatch.setattr(
            service,
            "get_document",
            AsyncMock(return_value=MagicMock(id=uuid.uuid4(), collection_name="docs")),
        )
        await service.complete_ingestion(
            "doc",
            vector_document_id="new-vector-doc",
            chunk_count=9,
            replaced_document_id="old-vector-doc",
        )
        await _run_deferred(db)

        assert deleted == [stale.id]
        storage.delete.assert_not_awaited()

    async def test_an_ingest_that_replaced_nothing_looks_for_no_stale_row(self, monkeypatch):
        superseded = AsyncMock(return_value=[])

        monkeypatch.setattr(rag_document_repo, "update_status", AsyncMock())
        monkeypatch.setattr(rag_document_repo, "get_superseded", superseded)

        service = RAGDocumentService(MagicMock())
        monkeypatch.setattr(
            service,
            "get_document",
            AsyncMock(return_value=MagicMock(id=uuid.uuid4(), collection_name="docs")),
        )
        await service.complete_ingestion(
            "doc",
            vector_document_id="new-vector-doc",
            chunk_count=9,
            replaced_document_id=None,
        )

        superseded.assert_not_awaited()
