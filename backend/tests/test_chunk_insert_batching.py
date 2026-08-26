"""How many statements writing a document's chunks costs.

#950. `insert_document` ran one `INSERT` per chunk in a Python loop, inside one
open transaction. At the default `chunk_size` a 200-page PDF is on the order of
one to three thousand chunks, so ingesting it was that many sequential asyncpg
round trips: a second or two on a local socket, five to fifteen against a managed
Postgres at 3-5ms - spent holding a connection while it waited.

These count statements rather than time them, because the count is what the
change is: it must not scale with the number of chunks. The integration half
proves the `executemany` actually writes every row, which a counted mock cannot.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rag import vectorstore as vectorstore_module
from app.services.rag.models import (
    Document,
    DocumentMetadata,
    DocumentPage,
    DocumentPageChunk,
)
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio


def _document(*, chunks: int) -> Document:
    document = Document(
        pages=[DocumentPage(page_num=1, content="body")],
        metadata=DocumentMetadata(filename="handbook.pdf", filesize=10, filetype="pdf"),
    )
    # `parent_doc_id` the way the splitter sets it (`documents.py:685`); the
    # model validator only connects pages, not the chunks assigned after it.
    document.chunked_pages = [
        DocumentPageChunk(
            chunk_content=f"chunk {index}",
            chunk_num=index,
            page_num=1,
            content=f"chunk {index}",
            parent_doc_id=document.id,
        )
        for index in range(chunks)
    ]
    return document


class RecordingSession:
    """A session that records the parameters each `execute` was given."""

    def __init__(self) -> None:
        self.calls: list[object] = []
        self.commits = 0
        self.on_execute: Callable[[], None] | None = None

    async def __aenter__(self) -> RecordingSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: object, params: object = None) -> MagicMock:
        if self.on_execute is not None:
            self.on_execute()
        self.calls.append(params)
        return MagicMock()

    async def commit(self) -> None:
        self.commits += 1


def _store(session: RecordingSession, *, dim: int = 3) -> PgVectorStore:
    """The real `insert_document`, with only the collection and embedder stubbed.

    `_ensure_collection` is replaced because it is DDL this is not about; what
    stays real is the statement building and the loop over batches, which is the
    whole of the change.
    """
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = lambda: session  # ty: ignore[invalid-assignment]
    embedder = MagicMock(
        embed_document=MagicMock(side_effect=lambda doc: [[0.0] * dim] * len(doc.chunked_pages))
    )
    store._ensure_collection = AsyncMock()  # ty: ignore[invalid-assignment]
    store._for_collection = AsyncMock(return_value=(embedder, dim))  # ty: ignore[invalid-assignment]
    return store


class TestHowManyStatementsOneDocumentCosts:
    async def test_a_document_of_many_chunks_is_written_in_batches(self, monkeypatch):
        """The statement count follows the batch size, not the chunk count."""
        monkeypatch.setattr(vectorstore_module, "_CHUNK_INSERT_BATCH", 100)
        session = RecordingSession()

        await _store(session).insert_document("docs", _document(chunks=250), organization_id=None)

        assert len(session.calls) == 3
        assert [len(batch) for batch in session.calls] == [100, 100, 50]  # ty: ignore[invalid-argument-type]
        assert session.commits == 1

    async def test_a_document_within_one_batch_is_one_statement(self, monkeypatch):
        """The common case - a short document - is a single round trip."""
        monkeypatch.setattr(vectorstore_module, "_CHUNK_INSERT_BATCH", 200)
        session = RecordingSession()

        await _store(session).insert_document("docs", _document(chunks=7), organization_id=None)

        assert len(session.calls) == 1
        assert len(session.calls[0]) == 7  # ty: ignore[invalid-argument-type]

    async def test_the_statement_count_does_not_grow_with_the_chunk_count(self, monkeypatch):
        """Ten times the chunks must not be ten times the statements, which is
        the only thing distinguishing this from the loop it replaced."""
        monkeypatch.setattr(vectorstore_module, "_CHUNK_INSERT_BATCH", 500)
        small, large = RecordingSession(), RecordingSession()

        await _store(small).insert_document("docs", _document(chunks=40), organization_id=None)
        await _store(large).insert_document("docs", _document(chunks=400), organization_id=None)

        assert len(small.calls) == len(large.calls) == 1

    async def test_every_chunk_is_in_the_parameters_exactly_once(self, monkeypatch):
        """Batching is only correct if nothing is dropped at a boundary."""
        monkeypatch.setattr(vectorstore_module, "_CHUNK_INSERT_BATCH", 3)
        session = RecordingSession()
        document = _document(chunks=10)

        await _store(session).insert_document("docs", document, organization_id=None)

        written = [row["id"] for batch in session.calls for row in batch]  # ty: ignore[invalid-argument-type]
        assert written == [chunk.chunk_id for chunk in document.chunked_pages]

    async def test_each_row_carries_its_own_metadata_and_vector(self, monkeypatch):
        """The rows are built in a comprehension now, so a row taking the wrong
        chunk's page number or the wrong embedding would be silent."""
        monkeypatch.setattr(vectorstore_module, "_CHUNK_INSERT_BATCH", 200)
        session = RecordingSession()
        document = _document(chunks=4)
        for index, chunk in enumerate(document.chunked_pages):
            chunk.page_num = index + 1

        await _store(session).insert_document("docs", document, organization_id=None)

        rows = session.calls[0]
        assert [json.loads(row["metadata"])["page_num"] for row in rows] == [1, 2, 3, 4]  # ty: ignore[invalid-argument-type]
        assert [json.loads(row["metadata"])["chunk_num"] for row in rows] == [0, 1, 2, 3]  # ty: ignore[invalid-argument-type]
        assert {row["embedding"] for row in rows} == {"[0.0, 0.0, 0.0]"}  # ty: ignore[invalid-argument-type]

    async def test_each_batch_of_rows_is_built_when_its_statement_runs(self, monkeypatch):
        """Batching the statements without batching the rows fixes nothing.

        The embedding is rendered as text in these rows, tens of kilobytes each
        at 3072 dimensions, so materialising all of them first would hold better
        than 100MB of live strings for a long document - bounding what asyncpg
        receives while leaving the worker's memory where it was. Counted through
        `_build_chunk_metadata`, which runs once per row built: at each statement
        only that batch's rows exist, so the counts step. Building the whole list
        first reads as `[30, 30, 30]`.
        """
        monkeypatch.setattr(vectorstore_module, "_CHUNK_INSERT_BATCH", 10)
        session = RecordingSession()
        store = _store(session)
        built = 0
        original = store._build_chunk_metadata

        def counting(chunk: object, document: object) -> dict[str, object]:
            nonlocal built
            built += 1
            return original(chunk, document)  # ty: ignore[invalid-argument-type]

        store._build_chunk_metadata = counting  # ty: ignore[invalid-assignment]
        seen: list[int] = []
        session.on_execute = lambda: seen.append(built)

        await store.insert_document("docs", _document(chunks=30), organization_id=None)

        assert seen == [10, 20, 30]

    async def test_a_document_with_no_chunks_is_refused_before_any_statement(self):
        """Unchanged, and worth pinning: an empty parameter list would make
        `executemany` a silent no-op where the loop was a silent no-op too."""
        session = RecordingSession()

        with pytest.raises(ValueError, match="no chunked pages"):
            await _store(session).insert_document("docs", _document(chunks=0), organization_id=None)

        assert session.calls == []
