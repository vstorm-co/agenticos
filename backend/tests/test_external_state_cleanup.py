"""External-state cleanup survives the process that dispatched it (#1274, #1349).

A committed delete - an organization purge (`OrganizationService.purge`) or a RAG
collection drop (`KnowledgeBaseService.delete`, `RAGDocumentService`) - used to hand
its external cleanup, unlinking stored uploads and dropping vector tables, to an
in-process `spawn_after_commit` task that died with the process. It now submits a
durable Prefect deployment run: the run and its parameters are recorded on the
server and retried by a worker. These pin the two halves - the dispatch submits the
right run, and the cleanup it runs is idempotent and re-checks a shared collection
name before dropping it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.worker.tasks import teardown_tasks
from app.worker.tasks.teardown_tasks import (
    cleanup_external_state,
    dispatch_external_state_cleanup,
    external_state_cleanup_flow,
)

pytestmark = pytest.mark.anyio


class TestDispatch:
    async def test_it_submits_the_cleanup_as_its_own_deployment_run(self) -> None:
        """`run_deployment` records the run on the Prefect server; that is what
        makes the cleanup outlive the process that dispatched it."""
        run = AsyncMock()
        with patch.object(teardown_tasks, "run_deployment", run):
            await dispatch_external_state_cleanup(["a/one.txt"], ["docs"])

        run.assert_awaited_once_with(
            name="org-purge-cleanup/org-purge-cleanup",
            parameters={"storage_paths": ["a/one.txt"], "collections": ["docs"]},
            timeout=0,
        )

    async def test_a_purge_with_no_paths_still_submits_the_table_drops(self) -> None:
        run = AsyncMock()
        with patch.object(teardown_tasks, "run_deployment", run):
            await dispatch_external_state_cleanup([], ["docs"])

        run.assert_awaited_once_with(
            name="org-purge-cleanup/org-purge-cleanup",
            parameters={"storage_paths": [], "collections": ["docs"]},
            timeout=0,
        )

    async def test_it_chunks_a_large_path_list_across_bounded_runs(self) -> None:
        """A payload over Prefect's 512 KiB flow-parameter limit would be rejected
        after the rows are gone, so the paths are split across runs and each stays
        bounded; the table drops ride the first run only (#1274)."""
        paths = [f"u/{i}.txt" for i in range(teardown_tasks._MAX_PATHS_PER_RUN + 1)]
        run = AsyncMock()
        with patch.object(teardown_tasks, "run_deployment", run):
            await dispatch_external_state_cleanup(paths, ["docs"])

        assert run.await_count == 2
        first, second = run.await_args_list
        assert len(first.kwargs["parameters"]["storage_paths"]) == teardown_tasks._MAX_PATHS_PER_RUN
        assert first.kwargs["parameters"]["collections"] == ["docs"]
        assert second.kwargs["parameters"]["storage_paths"] == [paths[-1]]
        assert second.kwargs["parameters"]["collections"] == []

    async def test_a_transient_submission_failure_is_retried(self) -> None:
        run = AsyncMock(side_effect=[RuntimeError("prefect blip"), None])
        with (
            patch.object(teardown_tasks, "run_deployment", run),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            await dispatch_external_state_cleanup(["a/one.txt"], [])

        assert run.await_count == 2

    async def test_a_submission_that_keeps_failing_is_logged_not_raised(self) -> None:
        """A run that cannot be submitted has no row to reconstruct it, but one
        transient failure must not abort the rest, so it is logged rather than
        raised (#1274)."""
        run = AsyncMock(side_effect=RuntimeError("prefect down"))
        with (
            patch.object(teardown_tasks, "run_deployment", run),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            await dispatch_external_state_cleanup(["a/one.txt"], [])

        assert run.await_count == teardown_tasks._SUBMIT_ATTEMPTS


@asynccontextmanager
async def _db_ctx() -> Any:
    yield MagicMock(execute=AsyncMock())


def _patch_cleanup(*, referenced: list[str]) -> Any:
    """Patch everything `cleanup_external_state` reaches, so the store and the
    reference check are controllable. `referenced` names the collections a base
    still claims - those must not be dropped."""
    storage = MagicMock(delete=AsyncMock())
    store = MagicMock(delete_collection=AsyncMock())
    engine = MagicMock(dispose=AsyncMock())

    async def _list(_db: object, name: str) -> list[object]:
        return [MagicMock()] if name in referenced else []

    patches = [
        patch("app.services.file_storage.get_file_storage", return_value=storage),
        patch.object(teardown_tasks, "create_async_engine", return_value=engine),
        patch("app.services.rag.vectorstore.PgVectorStore", return_value=store),
        patch("app.services.rag.embeddings.EmbeddingService", return_value=MagicMock()),
        patch("app.db.session.get_worker_db_context", _db_ctx),
        patch("app.repositories.knowledge_base_repo.list_by_collection_name", new=_list),
    ]
    return storage, store, engine, patches


class TestTheCleanup:
    async def test_it_unlinks_every_file_and_drops_every_unreferenced_table(self) -> None:
        storage, store, engine, patches = _patch_cleanup(referenced=[])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = await cleanup_external_state(["u/a.txt", "u/b.txt"], ["docs", "wiki"])

        assert storage.delete.await_count == 2
        assert store.delete_collection.await_count == 2
        assert result == {"unlinked": 2, "dropped": 2}
        engine.dispose.assert_awaited_once()

    async def test_it_leaves_a_table_a_base_still_references(self) -> None:
        """`collection_name` is not tenant-unique, so a name a second org has
        claimed since the purge must keep its table (#913)."""
        storage, store, _engine, patches = _patch_cleanup(referenced=["wiki"])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = await cleanup_external_state([], ["docs", "wiki"])

        store.delete_collection.assert_awaited_once_with("docs")
        assert result == {"unlinked": 0, "dropped": 1}

    async def test_a_failed_unlink_or_drop_does_not_abort_the_rest(self) -> None:
        """Best-effort: a file already gone or a table that never existed is not a
        reason to abandon the cleanup a retry would otherwise repeat."""
        storage, store, _engine, patches = _patch_cleanup(referenced=[])
        storage.delete = AsyncMock(side_effect=OSError("gone"))
        store.delete_collection = AsyncMock(side_effect=SQLAlchemyError("no such table"))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = await cleanup_external_state(["u/a.txt"], ["docs"])

        assert result == {"unlinked": 1, "dropped": 0}

    async def test_no_collections_touches_no_store(self) -> None:
        """A purge that only left files behind builds no vector-store engine."""
        storage, _store, _engine, patches = _patch_cleanup(referenced=[])
        with (
            patches[0],
            patch.object(teardown_tasks, "create_async_engine") as make_engine,
            patches[2],
            patches[3],
            patches[4],
            patches[5],
        ):
            result = await cleanup_external_state(["u/a.txt"], [])

        make_engine.assert_not_called()
        assert result == {"unlinked": 1, "dropped": 0}

    async def test_it_locks_each_collection_before_dropping(self) -> None:
        """Each collection's re-check and drop are serialized against a concurrent
        claim of the same name by an advisory lock, so a base created in the window
        between them keeps its table (#1355, #913)."""
        from app.db.locks import LockScope

        _storage, _store, _engine, patches = _patch_cleanup(referenced=[])
        lock = AsyncMock()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patch("app.db.locks.hold_name", lock),
        ):
            await cleanup_external_state([], ["docs", "wiki"])

        assert [call.args[1:] for call in lock.await_args_list] == [
            (LockScope.COLLECTION_TEARDOWN, "docs"),
            (LockScope.COLLECTION_TEARDOWN, "wiki"),
        ]


class TestTheFlow:
    async def test_it_runs_the_cleanup(self) -> None:
        """The `@flow` wrapper is thin: it carries the durability and delegates the
        work to `cleanup_external_state`."""
        impl = AsyncMock(return_value={"unlinked": 1, "dropped": 1})
        with patch.object(teardown_tasks, "cleanup_external_state", impl):
            result = await external_state_cleanup_flow(["u/a.txt"], ["docs"])

        impl.assert_awaited_once_with(["u/a.txt"], ["docs"])
        assert result == {"unlinked": 1, "dropped": 1}
