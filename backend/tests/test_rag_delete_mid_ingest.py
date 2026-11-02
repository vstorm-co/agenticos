"""A settlement that finds its document deleted removes the chunks it wrote (#2565).

The delete purges by the row's vector id, which is `NULL` until the ingest settles,
so each settler is what has to clean up. The orderings against a real delete are
`tests/integration/test_document_delete_mid_ingest.py`.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.db.vector_tables import VectorScope
from app.repositories import rag_document_repo
from app.services.rag.models import IngestionResult, IngestionStatus
from app.services.rag_document import RAGDocumentService
from app.worker.jobs import DISCARD_VECTOR_DOCUMENT, DiscardVectorDocument, IngestDocument
from app.worker.tasks import rag_tasks, teardown_tasks

pytestmark = pytest.mark.anyio

DONE = IngestionResult(status=IngestionStatus.DONE, document_id="vec-1", chunk_count=2)


async def _complete(service: RAGDocumentService) -> bool:
    return await service.complete_ingestion(
        str(uuid.uuid4()),
        vector_document_id="vec-1",
        chunk_count=2,
        replaced_document_id=None,
        attempt=1,
    )


class TestCompletingAnIngest:
    async def test_a_row_already_gone_reports_it_rather_than_raising(self, monkeypatch) -> None:
        update = AsyncMock()
        monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=None))
        monkeypatch.setattr(rag_document_repo, "update_status", update)

        assert await _complete(RAGDocumentService(MagicMock())) is False
        update.assert_not_awaited()

    async def test_a_row_deleted_before_the_update_reports_it(self, monkeypatch) -> None:
        monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=MagicMock()))
        monkeypatch.setattr(rag_document_repo, "update_status", AsyncMock(return_value=None))
        monkeypatch.setattr(rag_document_repo, "is_present", AsyncMock(return_value=False))

        assert await _complete(RAGDocumentService(MagicMock())) is False

    async def test_a_superseded_attempt_is_not_mistaken_for_a_deletion(self, monkeypatch) -> None:
        """A newer retry owns the row: these chunks are not this settlement's to drop."""
        superseded = AsyncMock()
        monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=MagicMock()))
        monkeypatch.setattr(rag_document_repo, "update_status", AsyncMock(return_value=None))
        monkeypatch.setattr(rag_document_repo, "is_present", AsyncMock(return_value=True))
        monkeypatch.setattr(rag_document_repo, "get_superseded", superseded)

        assert await _complete(RAGDocumentService(MagicMock())) is True
        superseded.assert_not_awaited()

    async def test_a_settled_row_reports_it_was_recorded(self, monkeypatch) -> None:
        monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=MagicMock()))
        monkeypatch.setattr(rag_document_repo, "update_status", AsyncMock(return_value=MagicMock()))

        assert await _complete(RAGDocumentService(MagicMock())) is True


async def test_the_delete_reads_the_vector_id_from_the_deleted_row() -> None:
    """`RETURNING`, so a settlement committed after the caller loaded the row is seen."""
    result = MagicMock()
    result.all.return_value = [("rag/a.md", "vec-1")]
    db = MagicMock(execute=AsyncMock(return_value=result), flush=AsyncMock())
    doc_id = uuid.uuid4()

    deleted = await rag_document_repo.delete_with_vectors(db, doc_id)

    assert deleted.vector_document_ids == ["vec-1"]
    assert deleted.storage_paths == ["rag/a.md"]
    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert sql.startswith("DELETE FROM rag_documents WHERE rag_documents.id =")
    assert "RETURNING rag_documents.storage_path, rag_documents.vector_document_id" in sql


@pytest.mark.parametrize("found", [True, False])
async def test_presence_is_a_query_not_the_sessions_cached_row(found: bool) -> None:
    """A column select, which the identity map cannot answer from a loaded row."""
    db = MagicMock(scalar=AsyncMock(return_value=uuid.uuid4() if found else None))

    assert await rag_document_repo.is_present(db, uuid.uuid4()) is found
    sql = str(db.scalar.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert sql.startswith("SELECT rag_documents.id")
    assert "WHERE rag_documents.id =" in sql


@asynccontextmanager
async def _session() -> AsyncIterator[MagicMock]:
    yield MagicMock()


SCOPE = VectorScope(tenant=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


class TestQueueingTheRemoval:
    async def test_the_job_carries_the_scope_the_chunks_were_stamped_with(
        self, monkeypatch
    ) -> None:
        """A job, in the settlement's transaction: the row is gone, so a removal
        that could only log its failure would leave the chunks searchable for good."""
        queued = AsyncMock()
        monkeypatch.setattr("app.services.rag_document.enqueue", queued)
        db = MagicMock()

        await RAGDocumentService(db).discard_untracked("docs", "vec-1", scope=SCOPE)

        assert queued.await_args.args[:2] == (db, DISCARD_VECTOR_DOCUMENT)
        assert queued.await_args.args[2] == DiscardVectorDocument(
            collection="docs",
            vector_document_id="vec-1",
            tenant=SCOPE.tenant,
            knowledge_base_id=SCOPE.knowledge_base_id,
        )

    @pytest.mark.security
    async def test_the_job_deletes_only_within_that_scope(self, monkeypatch) -> None:
        store = MagicMock(delete_document=AsyncMock())

        @asynccontextmanager
        async def vector_store() -> AsyncIterator[MagicMock]:
            yield store

        monkeypatch.setattr(teardown_tasks, "_vector_store", vector_store)

        await teardown_tasks.discard_vector_document(
            DiscardVectorDocument(
                collection="docs",
                vector_document_id="vec-1",
                tenant=SCOPE.tenant,
                knowledge_base_id=SCOPE.knowledge_base_id,
            )
        )

        store.delete_document.assert_awaited_once_with(
            "docs",
            "vec-1",
            VectorScope(tenant=SCOPE.tenant, knowledge_base_id=SCOPE.knowledge_base_id),
        )

    def test_the_worker_runs_it(self) -> None:
        from app.worker.handlers import production

        assert DISCARD_VECTOR_DOCUMENT.kind in production()


def _documents(*, recorded: bool) -> MagicMock:
    return MagicMock(
        complete_ingestion=AsyncMock(return_value=recorded),
        discard_untracked=AsyncMock(),
        add_claims=AsyncMock(),
    )


@asynccontextmanager
async def _session() -> AsyncIterator[MagicMock]:
    yield MagicMock()


class TestASyncSettlingADeletedRow:
    async def test_it_queues_the_removal_under_the_ingesters_scope(self) -> None:
        documents = _documents(recorded=False)

        with (
            patch.object(rag_tasks, "get_worker_db_context", new=_session),
            patch("app.services.rag_document.RAGDocumentService", return_value=documents),
        ):
            settled = await rag_tasks._settle_document_row(
                str(uuid.uuid4()),
                DONE,
                ingester=MagicMock(scope=SCOPE),
                collection_name="docs",
                inherited=frozenset({uuid.uuid4()}),
            )

        # The sync then counts it as neither ingested nor failed.
        assert settled is False

        documents.discard_untracked.assert_awaited_once_with("docs", "vec-1", scope=SCOPE)
        # Nothing to claim: the row is gone.
        documents.add_claims.assert_not_awaited()

    async def test_a_recorded_row_keeps_its_chunks(self) -> None:
        documents = _documents(recorded=True)

        with (
            patch.object(rag_tasks, "get_worker_db_context", new=_session),
            patch("app.services.rag_document.RAGDocumentService", return_value=documents),
        ):
            settled = await rag_tasks._settle_document_row(
                str(uuid.uuid4()), DONE, ingester=MagicMock(scope=SCOPE), collection_name="docs"
            )

        assert settled is True
        documents.discard_untracked.assert_not_awaited()


@pytest.fixture
def worker() -> Any:
    """`ingest_document` with an ingest that wrote `vec-1`."""
    documents = _documents(recorded=False)
    documents.get_document = AsyncMock(
        return_value=MagicMock(organization_id=None, ingestion_config={}, knowledge_base_id=None)
    )
    documents.fail_ingestion = AsyncMock()

    @asynccontextmanager
    async def ingestion_service(**_: object) -> AsyncIterator[MagicMock]:
        yield MagicMock(ingest_file=AsyncMock(return_value=DONE))

    with (
        patch.object(rag_tasks, "get_worker_db_context", new=_session),
        patch.object(rag_tasks, "_ingestion_service", new=ingestion_service),
        patch.object(rag_tasks, "_record_embedding_spend", new=AsyncMock()),
        patch.object(rag_tasks, "IngestionConfigService") as config_service,
        patch("app.services.rag_document.RAGDocumentService", return_value=documents),
    ):
        config_service.return_value.build_processor = AsyncMock(return_value=MagicMock())
        yield documents


def _job() -> IngestDocument:
    return IngestDocument(
        rag_document_id=uuid.uuid4(),
        collection_name="docs",
        filepath="queued/a.md",
        source_path="a.md",
        replace=False,
        attempt=1,
    )


class TestAnUploadDeletedWhileItIndexed:
    async def test_its_removal_is_queued_and_the_job_ends(self, worker: MagicMock) -> None:
        outcome = await rag_tasks.ingest_document(_job())

        assert outcome == {"status": "deleted", "filename": "a.md"}
        # The row has no base, so the chunks were written deployment-wide.
        worker.discard_untracked.assert_awaited_once_with(
            "docs", "vec-1", scope=VectorScope(tenant=None)
        )
        # No failure is recorded on a row that is not there, and nothing is raised
        # into a retry that could only fail again.
        worker.fail_ingestion.assert_not_awaited()

    async def test_a_recorded_upload_removes_nothing(self, worker: MagicMock) -> None:
        worker.complete_ingestion = AsyncMock(return_value=True)

        outcome = await rag_tasks.ingest_document(_job())

        assert outcome["status"] == "done"
        worker.discard_untracked.assert_not_awaited()


@pytest.mark.parametrize("recorded", [True, False], ids=["recorded", "deleted"])
async def test_the_cli_queues_the_removal_for_a_row_deleted_meanwhile(
    monkeypatch, tmp_path, recorded: bool
) -> None:
    """Under the command's own scope, and never counted as ingested."""
    from app.commands import rag as rag_command

    (tmp_path / "handbook.md").write_text("body")
    documents = _documents(recorded=recorded)
    documents.create_document = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    documents.hold_ingestion_name = AsyncMock()
    documents.fail_ingestion = AsyncMock()
    ingestion = MagicMock(
        scope=VectorScope(tenant=None),
        existing_document=AsyncMock(return_value=MagicMock(document_id=None, content_hash=None)),
        ingest_file=AsyncMock(
            return_value=MagicMock(
                status=MagicMock(value="done"),
                document_id="vec-1",
                chunk_count=2,
                replaced_document_id=None,
                message="Successfully ingested 'handbook.md'",
                error_message=None,
            )
        ),
    )

    @asynccontextmanager
    async def _db() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    complete_sync = AsyncMock()
    monkeypatch.setattr(rag_command, "get_db_context", _db)
    monkeypatch.setattr(rag_command, "RAGDocumentService", lambda _db: documents)
    monkeypatch.setattr(
        rag_command,
        "RAGSyncService",
        lambda _db: MagicMock(
            create_sync_log=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            complete_sync=complete_sync,
        ),
    )

    await rag_command.ingest_path_async(
        path=str(tmp_path),
        collection="docs",
        recursive=True,
        vector_store=MagicMock(create_collection=AsyncMock()),
        processor=MagicMock(),
        ingestion=ingestion,
    )

    if recorded:
        documents.discard_untracked.assert_not_awaited()
    else:
        documents.discard_untracked.assert_awaited_once_with(
            "docs", "vec-1", scope=VectorScope(tenant=None)
        )
    assert complete_sync.await_args.kwargs["ingested"] == (1 if recorded else 0)
    assert complete_sync.await_args.kwargs["failed"] == 0
