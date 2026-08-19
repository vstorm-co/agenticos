"""Every vector store the ingestion worker builds is disposed with its work.

#948. `PgVectorStore.__init__` creates a pooled SQLAlchemy engine, and the three
flows in `app/worker/tasks/rag_tasks.py` each built one and disposed none. One
flow runs per uploaded document, so two hundred uploads meant two hundred pooled
engines abandoned in one worker process, each holding its checked-in connections
until the process exited. Somewhere short of a hundred documents the worker
reached `max_connections` and every query after that raised - including the ones
that would have marked a document failed, so the symptom was an upload stuck at
`processing` with a connection error in a log nobody was reading.

These count constructions against disposals rather than asserting a call, so
they fail for a store built on any path that does not close it - which is how the
early return in `_run_sync` was found: it built a store and then answered "path
not found".
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rag.models import IngestionStatus
from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio


class StoreLedger:
    """Counts the stores a flow builds and the ones it closes."""

    def __init__(self) -> None:
        self.built: list[MagicMock] = []
        self.closed: list[MagicMock] = []

    def __call__(self, *args: Any, **kwargs: Any) -> MagicMock:
        store = MagicMock()
        store.aclose = AsyncMock(side_effect=lambda: self.closed.append(store))
        self.built.append(store)
        return store

    @property
    def leaked(self) -> int:
        return len(self.built) - len(self.closed)


@asynccontextmanager
async def _worker_db() -> Any:
    yield MagicMock()


def _ingest_result(status: IngestionStatus = IngestionStatus.DONE) -> MagicMock:
    return MagicMock(
        status=status,
        document_id="vector-doc",
        chunk_count=3,
        replaced_document_id=None,
        error_message=None,
        message="",
    )


@asynccontextmanager
async def _worker(ledger: StoreLedger, *, ingest: AsyncMock | None = None) -> Any:
    """The worker module with its store constructor and its database replaced.

    `IngestionService` is left real: it is what holds the store the flow has to
    close, so a stand-in service would be a test of the stand-in.
    """
    with (
        patch.object(rag_tasks, "VectorStore", new=ledger),
        patch.object(rag_tasks, "EmbeddingService", new=MagicMock()),
        patch.object(rag_tasks, "get_worker_db_context", new=_worker_db),
        patch.object(rag_tasks, "_record_embedding_spend", new=AsyncMock()),
        patch.object(rag_tasks, "assert_organization_within_budget", new=AsyncMock()),
        patch.object(rag_tasks, "IngestionConfigService") as config_service,
        patch.object(rag_tasks.IngestionService, "ingest_file", new=ingest or AsyncMock()),
    ):
        config_service.return_value.build_processor = AsyncMock(return_value=MagicMock())
        yield config_service


class TestAnUploadsStore:
    async def test_ingesting_many_documents_leaves_no_store_open(self):
        """The count of live stores must not grow with the number of documents."""
        ledger = StoreLedger()
        documents = MagicMock(
            get_document=AsyncMock(
                return_value=MagicMock(organization_id=uuid.uuid4(), ingestion_config={})
            ),
            complete_ingestion=AsyncMock(),
        )

        async with _worker(ledger, ingest=AsyncMock(return_value=_ingest_result())):
            with patch("app.services.rag_document.RAGDocumentService", return_value=documents):
                for _ in range(5):
                    await rag_tasks._run_ingestion(
                        str(uuid.uuid4()), "docs", "queued/f.md", "f.md", False
                    )

        assert len(ledger.built) == 5
        assert ledger.leaked == 0

    async def test_a_failed_ingest_still_disposes_its_store(self):
        """The failure path is the one that mattered: a worker out of connections
        cannot record the failure that put it there."""
        ledger = StoreLedger()
        documents = MagicMock(
            get_document=AsyncMock(
                return_value=MagicMock(organization_id=None, ingestion_config={})
            ),
            fail_ingestion=AsyncMock(),
        )

        async with _worker(ledger, ingest=AsyncMock(side_effect=RuntimeError("provider refused"))):
            with patch("app.services.rag_document.RAGDocumentService", return_value=documents):
                with pytest.raises(RuntimeError):
                    await rag_tasks._run_ingestion(
                        str(uuid.uuid4()), "docs", "queued/f.md", "f.md", False
                    )

        assert ledger.leaked == 0

    async def test_an_ingest_that_returns_a_failure_disposes_its_store(self):
        """`ingest_file` reports a bad index by returning one, and that path
        raises after the store has been handed back."""
        ledger = StoreLedger()
        documents = MagicMock(
            get_document=AsyncMock(
                return_value=MagicMock(organization_id=None, ingestion_config={})
            ),
        )

        async with _worker(
            ledger, ingest=AsyncMock(return_value=_ingest_result(IngestionStatus.ERROR))
        ):
            with (
                patch("app.services.rag_document.RAGDocumentService", return_value=documents),
                patch.object(rag_tasks, "_update_status", new=AsyncMock()),
                pytest.raises(RuntimeError),
            ):
                await rag_tasks._run_ingestion(
                    str(uuid.uuid4()), "docs", "queued/f.md", "f.md", False
                )

        assert ledger.leaked == 0

    async def test_a_processor_that_cannot_be_built_builds_no_store(self):
        """The order inside the helper is load-bearing: the store used to be
        constructed first, so a parser the collection asks for and this build
        cannot provide left a pool nobody held a reference to."""
        ledger = StoreLedger()
        documents = MagicMock(
            get_document=AsyncMock(
                return_value=MagicMock(organization_id=None, ingestion_config={})
            ),
        )

        async with _worker(ledger) as config_service:
            config_service.return_value.build_processor = AsyncMock(
                side_effect=RuntimeError("no parser for that configuration")
            )
            with (
                patch("app.services.rag_document.RAGDocumentService", return_value=documents),
                pytest.raises(RuntimeError),
            ):
                await rag_tasks._run_ingestion(
                    str(uuid.uuid4()), "docs", "queued/f.md", "f.md", False
                )

        assert ledger.built == []


class TestASyncsStore:
    async def test_a_directory_sync_disposes_the_store_it_built(self, tmp_path: Path):
        ledger = StoreLedger()
        (tmp_path / "handbook.md").write_text("body")
        sync = MagicMock(
            get_sync_log=AsyncMock(return_value=MagicMock(status="running")),
            complete_sync=AsyncMock(),
        )
        documents = MagicMock(
            create_document=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            complete_ingestion=AsyncMock(),
        )

        async with _worker(ledger, ingest=AsyncMock(return_value=_ingest_result())):
            with (
                patch("app.services.rag_sync.RAGSyncService", return_value=sync),
                patch("app.services.rag_document.RAGDocumentService", return_value=documents),
                patch.object(rag_tasks, "_config_for_collection", new=AsyncMock()),
            ):
                await rag_tasks._run_sync(str(uuid.uuid4()), "local", "docs", "full", str(tmp_path))

        assert len(ledger.built) == 1
        assert ledger.leaked == 0

    async def test_a_sync_of_a_path_that_does_not_exist_builds_no_store(self, tmp_path: Path):
        """It used to build one first and then answer "path not found", so the
        cheapest possible refusal leaked a connection pool."""
        ledger = StoreLedger()

        async with _worker(ledger):
            with patch.object(rag_tasks, "_update_sync_log", new=AsyncMock()):
                answer = await rag_tasks._run_sync(
                    str(uuid.uuid4()), "local", "docs", "full", str(tmp_path / "absent")
                )

        assert answer["status"] == "error"
        assert ledger.built == []

    async def test_a_cancelled_sync_disposes_the_store_it_built(self, tmp_path: Path):
        """Cancellation returns from inside the file loop, past every dispose a
        caller might have written after it."""
        ledger = StoreLedger()
        (tmp_path / "handbook.md").write_text("body")
        sync = MagicMock(get_sync_log=AsyncMock(return_value=MagicMock(status="cancelled")))

        async with _worker(ledger):
            with (
                patch("app.services.rag_sync.RAGSyncService", return_value=sync),
                patch.object(rag_tasks, "_config_for_collection", new=AsyncMock()),
            ):
                answer = await rag_tasks._run_sync(
                    str(uuid.uuid4()), "local", "docs", "full", str(tmp_path)
                )

        assert answer["status"] == "cancelled"
        assert ledger.leaked == 0


class TestAConnectorSyncsStore:
    async def test_a_source_sync_disposes_the_store_it_built(self):
        ledger = StoreLedger()
        source = MagicMock(
            connector_type="gdrive",
            config={"folder_id": "abc"},
            collection_name="docs",
            sync_mode="full",
            organization_id=None,
        )
        sources = MagicMock(
            get_source=AsyncMock(return_value=source),
            update_after_sync=AsyncMock(),
            trigger_sync=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        )
        connector = MagicMock(list_files=AsyncMock(return_value=[]))

        async with _worker(ledger):
            with (
                patch.object(rag_tasks, "SyncSourceService", return_value=sources),
                patch.object(
                    rag_tasks.SyncSourceService,
                    "decrypt_config_dict",
                    new=staticmethod(lambda raw: raw),
                ),
                patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"gdrive": lambda: connector}),
                patch("app.services.rag_sync.RAGSyncService", return_value=MagicMock()),
                patch.object(rag_tasks, "_config_for_collection", new=AsyncMock()),
            ):
                await rag_tasks._run_source_sync(str(uuid.uuid4()), sync_log_id=str(uuid.uuid4()))

        assert len(ledger.built) == 1
        assert ledger.leaked == 0

    async def test_a_source_whose_connector_fails_disposes_the_store(self):
        ledger = StoreLedger()
        source = MagicMock(
            connector_type="gdrive",
            config={"folder_id": "abc"},
            collection_name="docs",
            sync_mode="full",
            organization_id=None,
        )
        sources = MagicMock(
            get_source=AsyncMock(return_value=source), update_after_sync=AsyncMock()
        )
        connector = MagicMock(list_files=AsyncMock(side_effect=RuntimeError("drive refused")))

        async with _worker(ledger):
            with (
                patch.object(rag_tasks, "SyncSourceService", return_value=sources),
                patch.object(
                    rag_tasks.SyncSourceService,
                    "decrypt_config_dict",
                    new=staticmethod(lambda raw: raw),
                ),
                patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"gdrive": lambda: connector}),
                patch("app.services.rag_sync.RAGSyncService", return_value=MagicMock()),
                patch.object(rag_tasks, "_config_for_collection", new=AsyncMock()),
            ):
                answer = await rag_tasks._run_source_sync(
                    str(uuid.uuid4()), sync_log_id=str(uuid.uuid4())
                )

        assert answer["status"] == "error"
        assert ledger.leaked == 0


class TestARequestsStore:
    """The API's fallback, which only runs on a deployment already in trouble."""

    async def test_a_request_that_builds_its_own_store_closes_it(self):
        """The lifespan catches a failed pgvector connection and carries on
        serving, so `request.state.vector_store` is absent and every request
        builds one - a degraded deployment spending its remaining connections."""
        from app.api import deps

        store = MagicMock(aclose=AsyncMock())
        request = MagicMock(state=SimpleNamespace())
        with patch.object(deps, "PgVectorStore", return_value=store):
            generator = deps.get_vectorstore(request, MagicMock())
            assert await anext(generator) is store
            with pytest.raises(StopAsyncIteration):
                await anext(generator)

        store.aclose.assert_awaited_once()

    async def test_the_lifespans_store_is_not_closed_by_a_request(self):
        """It belongs to the process, and shutdown disposes it. Closing it here
        would leave every later request holding a store with no pool."""
        from app.api import deps

        shared = MagicMock(aclose=AsyncMock())
        request = MagicMock(state=SimpleNamespace(vector_store=shared))
        generator = deps.get_vectorstore(request, MagicMock())
        assert await anext(generator) is shared
        with pytest.raises(StopAsyncIteration):
            await anext(generator)

        shared.aclose.assert_not_awaited()


class TestTheKnowledgeCapabilitysStore:
    async def test_shutdown_disposes_the_store_the_first_search_built(self):
        """One pool per API process, reachable from no request, so the lifespan's
        own `aclose` never saw it."""
        import app.agents.capabilities.knowledge._search as search_module

        store = MagicMock(aclose=AsyncMock())
        with (
            patch.object(search_module, "EmbeddingService"),
            patch.object(search_module, "PgVectorStore", return_value=store),
            patch.object(search_module, "RetrievalService"),
        ):
            search_module._retrieval_service = None
            search_module._vector_store = None
            try:
                search_module.get_retrieval_service()
                await search_module.aclose_retrieval_service()
            finally:
                search_module._retrieval_service = None
                search_module._vector_store = None

        store.aclose.assert_awaited_once()

    async def test_shutting_down_without_a_search_closes_nothing(self):
        """A deployment where no agent ever searched has no pool to release, and
        shutdown must not build one to close it."""
        import app.agents.capabilities.knowledge._search as search_module

        with patch.object(search_module, "PgVectorStore") as store_cls:
            search_module._retrieval_service = None
            search_module._vector_store = None
            await search_module.aclose_retrieval_service()

        store_cls.assert_not_called()

    async def test_the_next_search_after_a_shutdown_builds_a_fresh_store(self):
        """Both globals are reset, so nothing searches through a disposed pool."""
        import app.agents.capabilities.knowledge._search as search_module

        first = MagicMock(aclose=AsyncMock())
        second = MagicMock(aclose=AsyncMock())
        with (
            patch.object(search_module, "EmbeddingService"),
            patch.object(search_module, "PgVectorStore", side_effect=[first, second]),
            patch.object(search_module, "RetrievalService"),
        ):
            search_module._retrieval_service = None
            search_module._vector_store = None
            try:
                search_module.get_retrieval_service()
                await search_module.aclose_retrieval_service()
                search_module.get_retrieval_service()

                assert search_module._vector_store is second
            finally:
                search_module._retrieval_service = None
                search_module._vector_store = None
