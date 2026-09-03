"""Every engine the ingestion worker builds is disposed with its work.

#948, then #12. `PgVectorStore.__init__` used to create a pooled SQLAlchemy
engine, and the three flows in `app/worker/tasks/rag_tasks.py` each built one
and disposed none. One flow runs per uploaded document, so two hundred uploads
meant two hundred pooled engines abandoned in one worker process, each holding
its checked-in connections until the process exited - somewhere short of a
hundred documents the worker reached `max_connections` and every query after
that raised, including the ones that would have marked a document failed.

The store no longer owns an engine at all: `_ingestion_service` builds one per
piece of work and its exit disposes it. These tests count constructions against
disposals rather than asserting a call, so they fail for an engine built on any
path that does not close it - which is how the early return in `_run_sync` was
found: it built a store and then answered "path not found".

The API process is the other half of the same design: its stores ride the
application's own engine and own nothing to dispose, where each used to open a
private pool beside it.
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


class EngineLedger:
    """Counts the engines a flow builds and the ones it disposes."""

    def __init__(self) -> None:
        self.built: list[MagicMock] = []
        self.disposed: list[MagicMock] = []

    def __call__(self, *args: Any, **kwargs: Any) -> MagicMock:
        engine = MagicMock()
        engine.dispose = AsyncMock(side_effect=lambda: self.disposed.append(engine))
        self.built.append(engine)
        return engine

    @property
    def leaked(self) -> int:
        return len(self.built) - len(self.disposed)


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
async def _worker(ledger: EngineLedger, *, ingest: AsyncMock | None = None) -> Any:
    """The worker module with its engine factory and its database replaced.

    `IngestionService` and `_ingestion_service` are left real: they are what
    build the engine the flow has to dispose, so a stand-in would be a test of
    the stand-in.
    """
    with (
        patch.object(rag_tasks, "create_async_engine", new=ledger),
        patch.object(rag_tasks, "VectorStore", new=MagicMock()),
        patch.object(rag_tasks, "EmbeddingService", new=MagicMock()),
        patch.object(rag_tasks, "get_worker_db_context", new=_worker_db),
        patch.object(rag_tasks, "_record_embedding_spend", new=AsyncMock()),
        patch.object(rag_tasks, "assert_organization_within_budget", new=AsyncMock()),
        patch.object(rag_tasks, "IngestionConfigService") as config_service,
        patch.object(rag_tasks.IngestionService, "ingest_file", new=ingest or AsyncMock()),
    ):
        config_service.return_value.build_processor = AsyncMock(return_value=MagicMock())
        # A connector sync asks for the image model to record on each document's
        # row (#992), so the stand-in service has to answer awaitably.
        config_service.return_value.resolved_image_model = AsyncMock(return_value=None)
        yield config_service


class TestAnUploadsEngine:
    async def test_ingesting_many_documents_leaves_no_engine_open(self):
        """The count of live engines must not grow with the number of documents."""
        ledger = EngineLedger()
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

    async def test_a_failed_ingest_still_disposes_its_engine(self):
        """The failure path is the one that mattered: a worker out of connections
        cannot record the failure that put it there."""
        ledger = EngineLedger()
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

    async def test_an_ingest_that_returns_a_failure_disposes_its_engine(self):
        """`ingest_file` reports a bad index by returning one, and that path
        raises after the engine has been handed back."""
        ledger = EngineLedger()
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
                patch.object(rag_tasks, "_fail_document", new=AsyncMock()),
                pytest.raises(RuntimeError),
            ):
                await rag_tasks._run_ingestion(
                    str(uuid.uuid4()), "docs", "queued/f.md", "f.md", False
                )

        assert ledger.leaked == 0

    async def test_a_processor_that_cannot_be_built_builds_no_engine(self):
        """The order inside the helper is load-bearing: the store used to be
        constructed first, so a parser the collection asks for and this build
        cannot provide left a pool nobody held a reference to."""
        ledger = EngineLedger()
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


class TestASyncsEngine:
    async def test_a_directory_sync_disposes_the_engine_it_built(self, tmp_path: Path):
        ledger = EngineLedger()
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

    async def test_a_sync_of_a_path_that_does_not_exist_builds_no_engine(self, tmp_path: Path):
        """It used to build one first and then answer "path not found", so the
        cheapest possible refusal leaked a connection pool."""
        ledger = EngineLedger()

        async with _worker(ledger):
            with patch.object(rag_tasks, "_update_sync_log", new=AsyncMock()):
                answer = await rag_tasks._run_sync(
                    str(uuid.uuid4()), "local", "docs", "full", str(tmp_path / "absent")
                )

        assert answer["status"] == "error"
        assert ledger.built == []

    async def test_a_cancelled_sync_disposes_the_engine_it_built(self, tmp_path: Path):
        """Cancellation returns from inside the file loop, past every dispose a
        caller might have written after it."""
        ledger = EngineLedger()
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


class TestAConnectorSyncsEngine:
    async def test_a_source_sync_disposes_the_engine_it_built(self):
        ledger = EngineLedger()
        source = MagicMock(
            connector_type="gdrive",
            config={"folder_id": "abc"},
            collection_name="docs",
            sync_mode="full",
            # A `UUID`, not a string: `get_source` answers with the *model*, whose
            # columns are `PG_UUID(as_uuid=True)`. A fixture holding a string is
            # what let `UUID(source.organization_id)` past review, and that raises
            # on every real sync.
            organization_id=uuid.uuid4(),
            secret_id=None,
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
                patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"gdrive": lambda: connector}),
                patch("app.services.rag_sync.RAGSyncService", return_value=MagicMock()),
                patch.object(rag_tasks, "_knowledge_base_for", new=AsyncMock(return_value=None)),
            ):
                await rag_tasks._run_source_sync(str(uuid.uuid4()), sync_log_id=str(uuid.uuid4()))

        assert len(ledger.built) == 1
        assert ledger.leaked == 0

    async def test_a_source_whose_connector_fails_disposes_the_engine(self):
        ledger = EngineLedger()
        source = MagicMock(
            connector_type="gdrive",
            config={"folder_id": "abc"},
            collection_name="docs",
            sync_mode="full",
            # A `UUID`, not a string: `get_source` answers with the *model*, whose
            # columns are `PG_UUID(as_uuid=True)`. A fixture holding a string is
            # what let `UUID(source.organization_id)` past review, and that raises
            # on every real sync.
            organization_id=uuid.uuid4(),
            secret_id=None,
        )
        sources = MagicMock(
            get_source=AsyncMock(return_value=source), update_after_sync=AsyncMock()
        )
        connector = MagicMock(list_files=AsyncMock(side_effect=RuntimeError("drive refused")))

        async with _worker(ledger):
            with (
                patch.object(rag_tasks, "SyncSourceService", return_value=sources),
                patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"gdrive": lambda: connector}),
                patch("app.services.rag_sync.RAGSyncService", return_value=MagicMock()),
                patch.object(rag_tasks, "_knowledge_base_for", new=AsyncMock(return_value=None)),
            ):
                answer = await rag_tasks._run_source_sync(
                    str(uuid.uuid4()), sync_log_id=str(uuid.uuid4())
                )

        assert answer["status"] == "error"
        assert ledger.leaked == 0


class TestTheProcessEngineStore:
    """The API's stores ride the application engine and own nothing to dispose."""

    def test_the_factory_binds_the_vector_engine_and_the_platform_resolver(self):
        """The two invariants every process-store site used to spell by hand -
        the engine and the resolver one of five sites once forgot (#306) - live
        in the factory and nowhere else. The engine is the process's *vector*
        pool, deliberately not the request pool: a handler already holds a
        request connection while the store asks for a second, so one shared
        pool turns saturation into a circular wait."""
        from app.db.session import engine, vector_engine
        from app.services.embedding_resolution import embeddings_for_collection
        from app.services.rag import vectorstore

        with patch.object(vectorstore, "PgVectorStore") as store_cls:
            store = vectorstore.process_vector_store(MagicMock(), MagicMock())

        assert store is store_cls.return_value
        assert store_cls.call_args.kwargs["engine"] is vector_engine
        assert store_cls.call_args.kwargs["engine"] is not engine
        assert store_cls.call_args.kwargs["resolver"] is embeddings_for_collection

    async def test_a_request_without_a_lifespan_store_builds_a_process_store(self):
        """The lifespan's store is absent when the embedding warmup failed, and
        the per-request fallback used to open a pooled engine of its own - a
        degraded deployment spending its remaining connections (#948)."""
        from app.api import deps

        request = MagicMock(state=SimpleNamespace())
        with patch.object(deps, "process_vector_store") as factory:
            store = deps.get_vectorstore(request, MagicMock())

        assert store is factory.return_value

    async def test_the_lifespans_store_is_handed_through_untouched(self):
        """It belongs to the process; a request neither rebuilds nor closes it."""
        from app.api import deps

        shared = MagicMock()
        request = MagicMock(state=SimpleNamespace(vector_store=shared))
        with patch.object(deps, "process_vector_store") as factory:
            assert deps.get_vectorstore(request, MagicMock()) is shared

        factory.assert_not_called()


class TestTheKnowledgeCapabilitysStore:
    def test_a_search_off_the_pooled_loop_builds_an_unpooled_store(self):
        """The capability's cached store used to open the second private pool an
        API process ran (#948). It rides the pool-less engine when the loop it is
        on does not own the process's pools - an agent inside a Prefect flow -
        because a pooled connection belongs to the loop that opened it."""
        import app.agents.capabilities.knowledge._search as search_module

        with (
            patch.object(search_module, "on_the_pooled_loop", return_value=False),
            patch.object(search_module, "EmbeddingService"),
            patch.object(search_module, "unpooled_vector_store") as factory,
            patch.object(search_module, "RetrievalService") as retrieval_cls,
        ):
            search_module.reset_retrieval_service()
            try:
                search_module.get_retrieval_service()
            finally:
                search_module.reset_retrieval_service()

        assert retrieval_cls.call_args.args[0] is factory.return_value

    def test_a_search_on_the_pooled_loop_keeps_the_process_store(self):
        """The API keeps the bounded pool. `NullPool` opens a connection per
        checkout and caps nothing, so serving every request from it would let a
        burst of concurrent runs reach `max_connections` where the pool queues -
        and on this loop the store is the one the lifespan and every request
        already share."""
        import app.agents.capabilities.knowledge._search as search_module

        with (
            patch.object(search_module, "on_the_pooled_loop", return_value=True),
            patch.object(search_module, "EmbeddingService"),
            patch.object(search_module, "process_vector_store") as factory,
            patch.object(search_module, "RetrievalService") as retrieval_cls,
        ):
            search_module.reset_retrieval_service()
            try:
                assert search_module.get_retrieval_service() is retrieval_cls.return_value
                search_module.get_retrieval_service()
            finally:
                search_module.reset_retrieval_service()

        assert retrieval_cls.call_args.args[0] is factory.return_value
        assert factory.call_count == 1

    def test_the_next_search_after_a_reset_builds_a_fresh_store(self):
        """Shutdown disposes the process engine, so a shutdown followed by more
        work - a test, a reload - must not search through the stale store."""
        import app.agents.capabilities.knowledge._search as search_module

        with (
            patch.object(search_module, "on_the_pooled_loop", return_value=False),
            patch.object(search_module, "EmbeddingService"),
            patch.object(search_module, "unpooled_vector_store") as factory,
            patch.object(search_module, "RetrievalService", side_effect=lambda *a, **k: object()),
        ):
            search_module.reset_retrieval_service()
            try:
                first = search_module.get_retrieval_service()
                search_module.reset_retrieval_service()
                second = search_module.get_retrieval_service()
            finally:
                search_module.reset_retrieval_service()

        assert first is not second
        assert factory.call_count == 2

    def test_the_off_loop_engine_caches_no_connection_to_hand_over(self):
        """The store a foreign loop is handed must be usable from that loop.

        A pooled asyncpg connection belongs to the loop that opened it, so a
        store cached for the life of the process and shared by two loops in one
        worker handed the second a connection made on the first
        (`InterfaceError: attached to a different loop`) (#1079). `NullPool`
        keeps no connection to hand over, which is the whole of the fix: assert
        the engine's pool class, because a pooled engine here passes every
        single-loop test and fails only in a worker running two flows."""
        from sqlalchemy.pool import NullPool

        from app.db.session import agent_vector_engine, vector_engine
        from app.services.embedding_resolution import embeddings_for_collection
        from app.services.rag import vectorstore

        with patch.object(vectorstore, "PgVectorStore") as store_cls:
            store = vectorstore.unpooled_vector_store(MagicMock(), MagicMock())

        assert store is store_cls.return_value
        assert store_cls.call_args.kwargs["engine"] is agent_vector_engine
        assert store_cls.call_args.kwargs["engine"] is not vector_engine
        assert store_cls.call_args.kwargs["resolver"] is embeddings_for_collection
        assert isinstance(agent_vector_engine.pool, NullPool)

    async def test_one_unpooled_store_serves_two_event_loops(self):
        """Off the pooled loop the store is held across loops, and that is only
        safe because it caches no connection: the same instance answers a second
        loop rather than being rebuilt per loop, and rebuilding per loop could
        not dispose the pool of a loop that had moved on anyway (#1079)."""
        import asyncio

        import app.agents.capabilities.knowledge._search as search_module

        with (
            patch.object(search_module, "on_the_pooled_loop", return_value=False),
            patch.object(search_module, "EmbeddingService"),
            patch.object(search_module, "unpooled_vector_store"),
            patch.object(search_module, "RetrievalService", side_effect=lambda *a, **k: object()),
        ):
            search_module.reset_retrieval_service()
            try:
                on_this_loop = search_module.get_retrieval_service()

                def on_another_loop() -> object:
                    return asyncio.run(_ask())

                async def _ask() -> object:
                    return search_module.get_retrieval_service()

                elsewhere = await asyncio.to_thread(on_another_loop)
            finally:
                search_module.reset_retrieval_service()

        assert elsewhere is on_this_loop


class TestWhichLoopOwnsThePools:
    """`get_db_context` is reached from five worker flows and from an agent's
    embedding resolver, each on a loop of its own (#1079)."""

    async def test_an_unclaimed_loop_gets_an_engine_of_its_own(self):
        """No lifespan has run - a worker process, the CLI, this test - so
        nothing owns the pools and a session must not borrow them."""
        from app.db import session as session_module

        with patch.object(session_module, "get_worker_db_context") as per_call:
            async with session_module.get_db_context() as db:
                assert db is per_call.return_value.__aenter__.return_value

    async def test_the_claiming_loop_gets_the_pooled_session(self):
        """The API's own loop serves every request and disposes the pools at
        shutdown, so it is the one loop that may check out of them."""
        from app.db import session as session_module

        session_module.claim_pooled_engines()
        try:
            assert session_module.on_the_pooled_loop() is True
            with patch.object(session_module, "_managed_session") as pooled:
                async with session_module.get_db_context() as db:
                    assert db is pooled.return_value.__aenter__.return_value
            assert pooled.call_args.args[0] is session_module.async_session_maker
        finally:
            session_module.release_pooled_engines()

    async def test_the_claim_does_not_outlive_the_loop_that_made_it(self):
        """A test or a reload runs a second lifespan on a second loop; a stale
        stamp would tell it that it owns pools bound to a loop that has gone."""
        import asyncio

        from app.db import session as session_module

        def claim_on_another_loop() -> None:
            asyncio.run(_claim())

        async def _claim() -> None:
            session_module.claim_pooled_engines()

        await asyncio.to_thread(claim_on_another_loop)
        try:
            assert session_module.on_the_pooled_loop() is False
        finally:
            session_module.release_pooled_engines()

    def test_no_loop_at_all_owns_nothing(self):
        """Import-time and sync-context callers ask this too."""
        from app.db import session as session_module

        assert session_module.on_the_pooled_loop() is False

    async def test_shutdown_gives_the_claim_up(self):
        """`close_db` disposes the pools; leaving them claimed would let work
        after the shutdown check out of a disposed engine."""
        from unittest.mock import AsyncMock

        from app.db import session as session_module

        session_module.claim_pooled_engines()
        disposable = MagicMock(dispose=AsyncMock())
        with (
            patch.object(session_module, "engine", disposable),
            patch.object(session_module, "vector_engine", disposable),
            patch.object(session_module, "agent_vector_engine", disposable),
        ):
            await session_module.close_db()

        assert disposable.dispose.await_count == 3

        assert session_module.on_the_pooled_loop() is False
