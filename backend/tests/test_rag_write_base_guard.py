"""A chunk write checks its knowledge base in the transaction that inserts it (#2561).

The lock itself, against a real delete, is `TestAnIngestRacingItsBasesDelete` in
`tests/integration/test_deletion_reconciliation.py`.
"""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.db.vector_tables import VectorScope
from app.repositories import knowledge_base_repo
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
    """Records each statement it runs, and each base held on it."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.commits = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: object, params: object = None) -> MagicMock:
        self.statements.append(str(statement))
        return MagicMock()

    async def commit(self) -> None:
        self.commits += 1


def _store(session: _Session) -> PgVectorStore:
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = lambda: session  # ty: ignore[invalid-assignment]
    embedder = MagicMock(embed_document=lambda doc: [[0.0] * 3] * len(doc.chunked_pages))
    store._ensure_collection = AsyncMock()  # ty: ignore[invalid-assignment]
    store._for_collection = AsyncMock(return_value=(embedder, 3))  # ty: ignore[invalid-assignment]
    return store


@pytest.fixture
def base_exists(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """The base's answer to the hold, which the hold records on the session it got."""
    answer = {"exists": True}

    async def hold(session: _Session, kb_id: object) -> bool:
        session.statements.append(f"hold {kb_id}")
        return answer["exists"]

    monkeypatch.setattr(knowledge_base_repo, "hold_key_share", hold)
    return answer


@pytest.mark.parametrize("found", [True, False])
async def test_the_hold_is_a_key_share_that_reports_the_base(found: bool) -> None:
    """`FOR KEY SHARE`, which two writes into one base both take without waiting;
    `with_for_update(key_share=True)` alone renders the self-conflicting
    `FOR NO KEY UPDATE`."""
    result = MagicMock()
    result.first.return_value = (BASE,) if found else None
    db = MagicMock(execute=AsyncMock(return_value=result))

    assert await knowledge_base_repo.hold_key_share(db, BASE) is found

    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert sql.endswith("FOR KEY SHARE")
    assert "knowledge_bases.id =" in sql


class TestTheWriteHoldsItsBase:
    async def test_the_base_is_held_in_the_inserts_own_transaction(
        self, base_exists: dict[str, bool]
    ) -> None:
        session = _Session()

        await _store(session).insert_document(
            "docs", _document(), VectorScope(tenant=None, knowledge_base_id=BASE)
        )

        hold, insert = session.statements
        assert hold == f"hold {BASE}"
        assert insert.lstrip().startswith("INSERT INTO")
        assert session.commits == 1

    async def test_a_deleted_base_gets_no_chunks(self, base_exists: dict[str, bool]) -> None:
        base_exists["exists"] = False
        session = _Session()

        with pytest.raises(KnowledgeBaseRemovedError) as raised:
            await _store(session).insert_document(
                "docs", _document(), VectorScope(tenant=None, knowledge_base_id=BASE)
            )

        assert raised.value.details == {"collection": "docs", "knowledge_base_id": str(BASE)}
        assert session.statements == [f"hold {BASE}"]
        assert session.commits == 0

    async def test_a_scope_with_no_base_takes_no_lock(self, base_exists: dict[str, bool]) -> None:
        """The CLI and a collection no base claims: there is no row to hold."""
        session = _Session()

        await _store(session).insert_document("docs", _document(), VectorScope(tenant=None))

        (insert,) = session.statements
        assert insert.lstrip().startswith("INSERT INTO")


class TestTheIngesterReportsTheRemovedBase:
    async def test_a_removed_base_is_an_index_failure_with_no_event(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An expected end of the race, so it is logged without the traceback the
        catch-all below it writes for an indexing that broke."""
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

        with caplog.at_level(logging.INFO, logger="app.services.rag.ingestion"):
            result = await ingester.ingest_file(Path("a.md"), "docs", replace=False)

        assert result.status is IngestionStatus.ERROR
        assert result.error_message == "gone"
        on_event.assert_not_awaited()
        assert [r.levelno for r in caplog.records] == [logging.INFO]
        assert caplog.records[0].exc_info is None
