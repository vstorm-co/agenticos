"""One precedence for "which stored document is this source_path" (#548).

`find_existing` and `get_existing_hash` used to walk the collection with
different rules: the id lookup checked every document for a `source_path`
match before falling back to `filename`, while the hash lookup interleaved
the two and let a filename hit block a later source-path match. Row order
decided which document each answered with — `get_documents` had no ORDER BY —
so the sync modes in `rag_tasks.py` compared a live file's hash against a
different document's `content_hash` than the one they were about to replace:
an unchanged file re-embedded on every sync, or a changed one skipped as
already current.

This module is template-inherited and outside the coverage gate, which is why
the precedence is pinned by name rather than trusted to a percentage.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rag.ingestion import IngestionService
from app.services.rag.models import DocumentInfo
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

        assert await service.find_existing("kb", "/srv/sync/handbook.pdf") == "doc-b"
        assert await service.get_existing_hash("kb", "/srv/sync/handbook.pdf") == "hash-b"

    async def test_a_filename_match_answers_when_no_source_path_does(self):
        service = _service(
            [
                _doc("doc-a", filename="other.pdf", content_hash="hash-a"),
                _doc("doc-b", filename="handbook.pdf", content_hash="hash-b"),
            ]
        )

        assert await service.find_existing("kb", "/srv/sync/handbook.pdf") == "doc-b"
        assert await service.get_existing_hash("kb", "/srv/sync/handbook.pdf") == "hash-b"

    async def test_no_match_answers_none_on_both_paths(self):
        service = _service([_doc("doc-a", filename="other.pdf", content_hash="hash-a")])

        assert await service.find_existing("kb", "/srv/sync/handbook.pdf") is None
        assert await service.get_existing_hash("kb", "/srv/sync/handbook.pdf") is None

    async def test_a_store_failure_answers_no_match_on_both_paths(self):
        store = MagicMock(get_documents=AsyncMock(side_effect=RuntimeError("connection refused")))
        service = IngestionService(processor=MagicMock(), vector_store=store)

        assert await service.find_existing("kb", "/srv/sync/handbook.pdf") is None
        assert await service.get_existing_hash("kb", "/srv/sync/handbook.pdf") is None

    async def test_a_document_without_a_stored_hash_answers_none_not_empty(self):
        """`_group_documents` fills an absent hash with "" — callers gate on truthiness."""
        service = _service(
            [_doc("doc-a", filename="handbook.pdf", source_path="/srv/sync/handbook.pdf")]
        )

        assert await service.get_existing_hash("kb", "/srv/sync/handbook.pdf") is None


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
