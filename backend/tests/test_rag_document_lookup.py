"""One precedence, one scan, for "which stored document is this file" (#548, #566).

`find_existing` and `get_existing_hash` used to walk the collection with
different rules: the id lookup checked every document for a `source_path`
match before falling back to `filename`, while the hash lookup interleaved
the two and let a filename hit block a later source-path match. Row order
decided which document each answered with — `get_documents` had no ORDER BY —
so the sync modes in `rag_tasks.py` compared a live file's hash against a
different document's `content_hash` than the one they were about to replace:
an unchanged file re-embedded on every sync, or a changed one skipped as
already current.

Both answers now come from one call, which is the structural half of that fix:
a caller cannot pair one document's id with another's hash if it cannot ask for
one without the other. It is also one full-collection read per file rather than
the two the sync modes did and the two more `ingest_file` added (#566).

This module is template-inherited and outside the coverage gate, which is why
the precedence is pinned by name rather than trusted to a percentage.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rag.ingestion import IngestionService, StoredDocument
from app.services.rag.models import (
    Document,
    DocumentInfo,
    DocumentMetadata,
    DocumentPage,
    DocumentPageChunk,
    IngestionStatus,
)
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio


def _service(docs: list[DocumentInfo]) -> IngestionService:
    store = MagicMock(get_documents=AsyncMock(return_value=docs))
    return IngestionService(processor=MagicMock(), vector_store=store)


def _doc(
    document_id: str, *, filename: str, source_path: str = "", content_hash: str = ""
) -> DocumentInfo:
    return DocumentInfo(
        document_id=document_id,
        filename=filename,
        additional_info={"source_path": source_path, "content_hash": content_hash},
    )


class TestOnePrecedenceForBothAnswers:
    async def test_the_id_and_the_hash_name_the_same_document(self):
        """A filename match ordered before the source-path match must not split the answer."""
        service = _service(
            [
                _doc(
                    "doc-a",
                    filename="handbook.pdf",
                    source_path="/old/handbook.pdf",
                    content_hash="hash-a",
                ),
                _doc(
                    "doc-b",
                    filename="handbook.pdf",
                    source_path="/srv/sync/handbook.pdf",
                    content_hash="hash-b",
                ),
            ]
        )

        existing = await service.existing_document("kb", "/srv/sync/handbook.pdf")

        assert existing == StoredDocument(document_id="doc-b", content_hash="hash-b")

    async def test_a_filename_match_answers_when_no_source_path_does(self):
        service = _service(
            [
                _doc("doc-a", filename="other.pdf", content_hash="hash-a"),
                _doc("doc-b", filename="handbook.pdf", content_hash="hash-b"),
            ]
        )

        existing = await service.existing_document("kb", "/srv/sync/handbook.pdf")

        assert existing == StoredDocument(document_id="doc-b", content_hash="hash-b")

    async def test_a_hash_match_is_the_last_resort_behind_the_filename(self):
        """The order `ingest_file` used to get by calling two helpers in turn.

        A document whose hash matches is the same content under another name, so
        it is a match - but only where neither the path nor the name found one,
        because a file that moved keeps its identity and a file that was copied
        does not take over the original's.
        """
        service = _service(
            [
                _doc("doc-a", filename="copy.pdf", content_hash="hash-x"),
                _doc("doc-b", filename="handbook.pdf", content_hash="hash-y"),
            ]
        )

        by_name = await service.existing_document(
            "kb", "/srv/sync/handbook.pdf", content_hash="hash-x"
        )
        by_hash = await service.existing_document(
            "kb", "/srv/sync/absent.pdf", content_hash="hash-x"
        )

        assert by_name.document_id == "doc-b"
        assert by_hash.document_id == "doc-a"

    async def test_a_hash_is_only_matched_when_one_was_offered(self):
        """An unhashed file must not match the first document that has no hash."""
        service = _service([_doc("doc-a", filename="other.pdf")])

        assert await service.existing_document("kb", "/srv/sync/handbook.pdf") == StoredDocument()

    async def test_no_match_answers_neither_id_nor_hash(self):
        service = _service([_doc("doc-a", filename="other.pdf", content_hash="hash-a")])

        assert await service.existing_document("kb", "/srv/sync/handbook.pdf") == StoredDocument()

    async def test_a_store_failure_answers_no_match(self):
        """A listing that cannot be read is not evidence the document is absent -
        but treating it as a match would delete one on a failed query."""
        store = MagicMock(get_documents=AsyncMock(side_effect=RuntimeError("connection refused")))
        service = IngestionService(processor=MagicMock(), vector_store=store)

        assert await service.existing_document("kb", "/srv/sync/handbook.pdf") == StoredDocument()

    async def test_a_document_without_a_stored_hash_answers_none_not_empty(self):
        """`_group_documents` fills an absent hash with "" — callers gate on truthiness."""
        service = _service(
            [_doc("doc-a", filename="handbook.pdf", source_path="/srv/sync/handbook.pdf")]
        )

        existing = await service.existing_document("kb", "/srv/sync/handbook.pdf")

        assert existing == StoredDocument(document_id="doc-a", content_hash=None)


class TestHowManyTimesTheCollectionIsRead:
    """#566. Three lookups over one listing, and a sync asked for two of them."""

    async def test_both_answers_cost_one_read(self):
        store = MagicMock(
            get_documents=AsyncMock(
                return_value=[
                    _doc(
                        "doc-a",
                        filename="handbook.pdf",
                        source_path="/srv/sync/handbook.pdf",
                        content_hash="hash-a",
                    )
                ]
            )
        )
        service = IngestionService(processor=MagicMock(), vector_store=store)

        existing = await service.existing_document("kb", "/srv/sync/handbook.pdf")

        assert existing.document_id and existing.content_hash
        assert store.get_documents.await_count == 1

    async def test_an_ingest_that_replaces_reads_the_collection_once(self):
        """It read it twice: once for the path, then again for the hash.

        Both are decided in one pass now, so the count is one whether the path
        matched or the hash did.
        """
        store = MagicMock(
            get_documents=AsyncMock(return_value=[]),
            insert_document=AsyncMock(),
            delete_document=AsyncMock(),
        )
        document = Document(
            pages=[DocumentPage(page_num=1, content="body")],
            metadata=DocumentMetadata(filename="handbook.pdf", filesize=4, filetype="pdf"),
        )
        document.chunked_pages = [
            DocumentPageChunk(chunk_content="body", chunk_num=0, page_num=1, content="body")
        ]
        document.metadata.content_hash = "hash-a"
        processor = MagicMock(process_file=AsyncMock(return_value=document))
        service = IngestionService(processor=processor, vector_store=store)

        result = await service.ingest_file(
            filepath=Path("handbook.pdf"),
            collection_name="kb",
            replace=True,
            source_path="/srv/sync/handbook.pdf",
        )

        assert result.status is IngestionStatus.DONE
        assert store.get_documents.await_count == 1


class TestGetDocumentsIsDeterministic:
    async def test_the_document_listing_carries_an_order_by(self):
        """The defence half of #548: arbitrary heap order is what let the two
        old lookups disagree, so the listing pins its own order. Asserted on
        the statement — the real consequence needs a populated Postgres, and a
        heap that happens to be ordered would pass a behavioural check falsely.
        """
        session = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        store = PgVectorStore.__new__(PgVectorStore)
        store.async_session = MagicMock(return_value=session_ctx)
        store._collection_exists = AsyncMock(return_value=True)  # type: ignore[method-assign]
        store._table = MagicMock(return_value="collection_kb")  # type: ignore[method-assign]

        await store.get_documents("kb")

        statement = str(session.execute.await_args.args[0])
        assert "ORDER BY parent_doc_id, id" in statement
