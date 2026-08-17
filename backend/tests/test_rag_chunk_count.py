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
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rag.ingestion import IngestionService
from app.services.rag.models import (
    Document,
    DocumentMetadata,
    DocumentPage,
    DocumentPageChunk,
    IngestionStatus,
)
from app.services.rag_document import RAGDocumentService
from app.worker.tasks.rag_tasks import _run_ingestion

pytestmark = pytest.mark.anyio


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
    return IngestionService(
        processor=processor,
        vector_store=MagicMock(insert_document=AsyncMock(), delete_document=AsyncMock()),
    )


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
                    status=IngestionStatus.DONE, document_id="vector-doc", chunk_count=42
                )
            )
        )

        with (
            patch("app.worker.tasks.rag_tasks.get_worker_db_context", _worker_db),
            patch("app.services.rag_document.RAGDocumentService", return_value=documents),
            patch("app.worker.tasks.rag_tasks.assert_organization_within_budget", new=AsyncMock()),
            patch(
                "app.worker.tasks.rag_tasks._ingestion_service_for",
                new=AsyncMock(return_value=ingestion),
            ),
            patch("app.worker.tasks.rag_tasks._record_embedding_spend", new=AsyncMock()),
        ):
            await _run_ingestion(document_id, "docs", "queued/handbook.md", "handbook.md", False)

        documents.complete_ingestion.assert_awaited_once_with(
            document_id, vector_document_id="vector-doc", chunk_count=42
        )

    def test_recording_an_ingest_cannot_omit_the_count(self):
        """The signature is the guard. Four call sites took a `chunk_count=0`
        default and nothing anywhere failed, so the number is keyword-only and
        required - a fifth caller does not compile rather than reporting zero.
        """
        parameter = inspect.signature(RAGDocumentService.complete_ingestion).parameters[
            "chunk_count"
        ]

        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty
