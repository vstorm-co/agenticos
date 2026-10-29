"""A chunk write checks its knowledge base in the transaction that inserts it (#2561).

An ingest's `still_wanted` gate answers before the write, on its own session, so a
base deleted beside a sibling that keeps the collection name - which reserves
nothing for that gate to see - could be deleted and purged between the gate and the
insert, and the chunks landed filed under a base nothing reads or removes. The write
now takes `FOR KEY SHARE` on the base's row in the insert's own transaction: the
lock `knowledge_base_repo.lock` already conflicts with (#1266). The integration half
is `TestAnIngestRacingItsBasesDelete` in `tests/integration/test_deletion_reconciliation.py`.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.db.vector_tables import VectorScope
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import (
    Document,
    DocumentMetadata,
    DocumentPage,
    DocumentPageChunk,
    IngestionStatus,
)
from app.services.rag.vectorstore import KnowledgeBaseRemovedError, PgVectorStore

pytestmark = pytest.mark.anyio

BASE = uuid4()


def _document() -> Document:
    document = Document(
        pages=[DocumentPage(page_num=1, content="body")],
        metadata=DocumentMetadata(filename="a.md", filesize=1, filetype="md"),
    )
    document.chunked_pages = [
        DocumentPageChunk(
            chunk_content="body", chunk_num=0, page_num=1, content="body", parent_doc_id=document.id
        )
    ]
    return document


class _Session:
    """Records each statement; the base lookup answers `base_row`."""

    def __init__(self, base_row: object | None) -> None:
        self.statements: list[tuple[str, object]] = []
        self.commits = 0
        self._base_row = base_row

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: object, params: object = None) -> MagicMock:
        self.statements.append((str(statement), params))
        return MagicMock(first=MagicMock(return_value=self._base_row))

    async def commit(self) -> None:
        self.commits += 1


def _store(session: _Session) -> PgVectorStore:
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = lambda: session  # ty: ignore[invalid-assignment]
    embedder = MagicMock(embed_document=lambda doc: [[0.0] * 3] * len(doc.chunked_pages))
    store._ensure_collection = AsyncMock()  # ty: ignore[invalid-assignment]
    store._for_collection = AsyncMock(return_value=(embedder, 3))  # ty: ignore[invalid-assignment]
    return store


class TestTheWriteHoldsItsBase:
    async def test_the_base_is_locked_in_the_inserts_own_transaction(self) -> None:
        session = _Session(base_row=(1,))

        await _store(session).insert_document(
            "docs", _document(), VectorScope(tenant=None, knowledge_base_id=BASE)
        )

        (lock, lock_params), (insert, _) = session.statements
        assert "FROM knowledge_bases" in lock
        assert "FOR KEY SHARE" in lock
        assert lock_params == {"kb": BASE}
        assert insert.lstrip().startswith("INSERT INTO")
        assert session.commits == 1

    async def test_a_deleted_base_gets_no_chunks(self) -> None:
        session = _Session(base_row=None)

        with pytest.raises(KnowledgeBaseRemovedError) as raised:
            await _store(session).insert_document(
                "docs", _document(), VectorScope(tenant=None, knowledge_base_id=BASE)
            )

        assert raised.value.details == {"collection": "docs", "knowledge_base_id": str(BASE)}
        assert len(session.statements) == 1
        assert session.commits == 0

    async def test_a_scope_with_no_base_takes_no_lock(self) -> None:
        """The CLI and a collection no base claims: there is no row to hold."""
        session = _Session(base_row=None)

        await _store(session).insert_document("docs", _document(), VectorScope(tenant=None))

        ((insert, _),) = session.statements
        assert insert.lstrip().startswith("INSERT INTO")


class TestTheIngesterReportsTheRemovedBase:
    async def test_a_removed_base_is_an_index_failure_with_no_event(self) -> None:
        store = MagicMock(
            find_existing_document=AsyncMock(return_value=None),
            insert_document=AsyncMock(
                side_effect=KnowledgeBaseRemovedError(
                    message="gone", details={"collection": "docs"}
                )
            ),
        )
        on_event = AsyncMock()
        processor = MagicMock(process_file=AsyncMock(return_value=_document()))
        ingester = IngestionService(processor, store, on_event=on_event)

        result = await ingester.ingest_file(Path("a.md"), "docs", replace=False)

        assert result.status is IngestionStatus.ERROR
        assert result.error_message == "gone"
        on_event.assert_not_awaited()
