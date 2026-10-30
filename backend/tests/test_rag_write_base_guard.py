"""A chunk write checks its knowledge base in the transaction that inserts it (#2561).

The lock itself, against a real delete, is `TestAnIngestRacingItsBasesDelete` in
`tests/integration/test_deletion_reconciliation.py`.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.core.exceptions import NotFoundError
from app.db.models.rag_document import DocumentStatus
from app.db.vector_tables import VectorScope
from app.repositories import knowledge_base_repo, rag_document_repo
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import (
    Document,
    DocumentMetadata,
    DocumentPage,
    DocumentPageChunk,
    IngestionResult,
    IngestionStatus,
)
from app.services.rag.vectorstore import KnowledgeBaseRemovedError, PgVectorStore
from app.worker.attempt import Attempt, running
from app.worker.jobs import IngestDocument
from app.worker.tasks import rag_tasks

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
    @pytest.mark.security
    @pytest.mark.parametrize("present", [True, False])
    async def test_a_tracked_write_checks_its_row_in_the_chunk_transaction(
        self, base_exists: dict[str, bool], monkeypatch: pytest.MonkeyPatch, present: bool
    ) -> None:
        session = _Session()
        document = _document()
        row_id = uuid4()
        document.metadata.rag_document_id = row_id
        hold = AsyncMock(return_value=present)
        monkeypatch.setattr(rag_document_repo, "hold_for_vector_write", hold)
        if present:
            await _store(session).insert_document(
                "docs", document, VectorScope(tenant=None, knowledge_base_id=BASE)
            )
            assert session.commits == 1
        else:
            with pytest.raises(KnowledgeBaseRemovedError, match="cleared"):
                await _store(session).insert_document(
                    "docs", document, VectorScope(tenant=None, knowledge_base_id=BASE)
                )
            assert session.statements == [f"hold {BASE}"]
            assert session.commits == 0
        hold.assert_awaited_once_with(session, row_id, collection="docs", knowledge_base_id=BASE)

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

        store = _store(session)
        with (
            patch.object(store, "_ensure_collection", new_callable=AsyncMock) as ensure,
            pytest.raises(KnowledgeBaseRemovedError) as raised,
        ):
            await store.insert_document(
                "docs", _document(), VectorScope(tenant=None, knowledge_base_id=BASE)
            )
        ensure.assert_not_awaited()
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


def _ingester(store: MagicMock) -> IngestionService:
    processor = MagicMock(process_file=AsyncMock(return_value=_document()))
    return IngestionService(processor, store)


class TestTheIngesterMarksARefusal:
    """A write skipped on purpose is `refused`, so the worker can end it rather
    than retry it (RR3-c1a)."""

    async def test_a_removed_base_is_a_refusal(self) -> None:
        store = MagicMock(
            find_existing_document=AsyncMock(return_value=None),
            insert_document=AsyncMock(
                side_effect=KnowledgeBaseRemovedError(message="gone", details={})
            ),
        )

        result = await _ingester(store).ingest_file(Path("a.md"), "docs", replace=False)

        assert result.refused is True

    async def test_a_collection_torn_down_is_a_refusal_with_a_written_reason(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        store = MagicMock(find_existing_document=AsyncMock(return_value=None))

        with caplog.at_level(logging.INFO, logger="app.services.rag.ingestion"):
            result = await _ingester(store).ingest_file(
                Path("a.md"), "docs", replace=False, still_wanted=AsyncMock(return_value=False)
            )

        assert result.status is IngestionStatus.ERROR
        assert result.refused is True
        assert result.error_message == "The collection was removed while this file was parsed"
        store.insert_document.assert_not_called()
        assert all(r.exc_info is None for r in caplog.records)

    async def test_an_index_that_broke_is_not_a_refusal(self) -> None:
        store = MagicMock(
            find_existing_document=AsyncMock(return_value=None),
            insert_document=AsyncMock(side_effect=RuntimeError("provider refused")),
        )

        result = await _ingester(store).ingest_file(Path("a.md"), "docs", replace=False)

        assert result.status is IngestionStatus.ERROR
        assert result.refused is False


REFUSAL = "The knowledge base was deleted while this file was being indexed"


@asynccontextmanager
async def _session() -> AsyncIterator[MagicMock]:
    yield MagicMock()


@pytest.fixture
def worker() -> Iterator[dict[str, Any]]:
    """`ingest_document` up to `ingest_file`, which answers what the test sets."""
    answer: dict[str, Any] = {}
    documents = MagicMock(
        get_document=AsyncMock(
            return_value=MagicMock(
                organization_id=None,
                ingestion_config={},
                knowledge_base_id=None,
                status=DocumentStatus.PROCESSING,
            )
        ),
        fail_ingestion=AsyncMock(),
    )
    ingester = MagicMock(ingest_file=AsyncMock(side_effect=lambda **_: answer["result"]))

    @asynccontextmanager
    async def ingestion_service(**_: object) -> AsyncIterator[MagicMock]:
        yield ingester

    with (
        patch.object(rag_tasks, "get_worker_db_context", new=_session),
        patch.object(rag_tasks, "_ingestion_service", new=ingestion_service),
        patch.object(rag_tasks, "_record_embedding_spend", new=AsyncMock()),
        patch.object(rag_tasks, "IngestionConfigService") as config_service,
        patch("app.services.rag_document.RAGDocumentService", return_value=documents),
    ):
        config_service.return_value.build_processor = AsyncMock(return_value=MagicMock())
        answer["documents"] = documents
        yield answer


def _job() -> IngestDocument:
    return IngestDocument(
        rag_document_id=uuid4(),
        collection_name="docs",
        filepath="queued/a.md",
        source_path="a.md",
        replace=False,
        attempt=1,
    )


class TestTheWorkerEndsARefusal:
    """A refused upload is terminal: the row fails with the written reason on the
    first attempt, the job returns rather than raising into a retry, and the log
    has a line at INFO, not a traceback (RR3-c1a)."""

    async def test_a_refusal_fails_the_row_and_is_not_retried(
        self, worker: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        worker["result"] = IngestionResult(
            status=IngestionStatus.ERROR, error_message=REFUSAL, refused=True
        )

        with (
            running(Attempt(number=1, of=2)),
            caplog.at_level(logging.INFO, logger="app.worker.tasks.rag_tasks"),
        ):
            outcome = await rag_tasks.ingest_document(_job())

        assert outcome["status"] == "refused"
        worker["documents"].fail_ingestion.assert_awaited_once()
        assert worker["documents"].fail_ingestion.await_args.kwargs["error_message"] == REFUSAL
        assert all(r.exc_info is None for r in caplog.records)
        assert max(r.levelno for r in caplog.records) == logging.INFO

    async def test_a_refusal_for_a_row_already_gone_records_nothing_quietly(
        self, worker: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        """A collection drop deletes the rows it tears down, so the row a
        `still_wanted` refusal would fail is usually gone."""
        worker["result"] = IngestionResult(
            status=IngestionStatus.ERROR, error_message=REFUSAL, refused=True
        )
        record = await worker["documents"].get_document()
        worker["documents"].get_document = AsyncMock(
            side_effect=[record, NotFoundError(message="Document not found")]
        )

        with caplog.at_level(logging.INFO, logger="app.worker.tasks.rag_tasks"):
            outcome = await rag_tasks.ingest_document(_job())

        assert outcome["status"] == "refused"
        worker["documents"].fail_ingestion.assert_not_awaited()
        assert max(r.levelno for r in caplog.records) == logging.INFO

    async def test_a_failure_that_is_not_a_refusal_is_still_retried(
        self, worker: dict[str, Any]
    ) -> None:
        worker["result"] = IngestionResult(status=IngestionStatus.ERROR, error_message="broke")

        with running(Attempt(number=1, of=2)), pytest.raises(RuntimeError):
            await rag_tasks.ingest_document(_job())

        worker["documents"].fail_ingestion.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("found", [True, False])
async def test_the_tracking_row_hold_is_scoped_and_uses_key_share(found: bool) -> None:
    row_id = uuid4()
    result = MagicMock()
    result.first.return_value = (row_id,) if found else None
    db = MagicMock(execute=AsyncMock(return_value=result))
    assert (
        await rag_document_repo.hold_for_vector_write(
            db, row_id, collection="docs", knowledge_base_id=BASE
        )
        is found
    )
    statement = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    assert str(statement).endswith("FOR KEY SHARE")
    assert set(statement.params.values()) == {row_id, "docs", BASE}


@pytest.mark.security
async def test_a_clear_with_no_vector_table_has_no_unsettled_vectors() -> None:
    from app.db.models.knowledge_base import KnowledgeBase

    db = MagicMock(scalar=AsyncMock(return_value=None), scalars=AsyncMock())
    kb = KnowledgeBase(id=BASE, collection_name="docs")
    assert await rag_document_repo.stored_vector_ids_at_clear(db, kb) == []
    db.scalars.assert_not_awaited()


class TestASyncSettlesARowItsBaseTookWithIt:
    """A source sync opens its row before the ingest; a base deleted meanwhile
    deletes the row too. Settling it raised `NotFoundError`, and the per-file
    loop's handler settled it again from inside `except`, so the second one
    escaped the loop and failed the whole run with a traceback."""

    @pytest.mark.parametrize(
        "result",
        [
            IngestionResult(status=IngestionStatus.ERROR, error_message=REFUSAL, refused=True),
            IngestionResult(status=IngestionStatus.DONE, document_id="vec-1", chunk_count=1),
        ],
        ids=["refused", "done"],
    )
    async def test_a_row_already_gone_is_noted_and_not_raised(
        self, result: IngestionResult, caplog: pytest.LogCaptureFixture
    ) -> None:
        gone = NotFoundError(message="Document not found")
        documents = MagicMock(
            fail_ingestion=AsyncMock(side_effect=gone),
            complete_ingestion=AsyncMock(side_effect=gone),
        )

        with (
            patch.object(rag_tasks, "get_worker_db_context", new=_session),
            patch("app.services.rag_document.RAGDocumentService", return_value=documents),
            caplog.at_level(logging.INFO, logger="app.worker.tasks.rag_tasks"),
        ):
            await rag_tasks._settle_document_row(str(uuid4()), result)

        assert max(r.levelno for r in caplog.records) == logging.INFO
        assert all(r.exc_info is None for r in caplog.records)
