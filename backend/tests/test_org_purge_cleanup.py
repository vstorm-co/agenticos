"""The org-teardown cleanup survives the process that dispatched it (#1274).

`OrganizationService.purge` used to hand its external cleanup - unlinking stored
uploads, dropping vector tables - to an in-process `spawn_after_commit` task,
which died with the process. It now submits a durable Prefect deployment run: the
run and its parameters are recorded on the server and retried by a worker. These
pin the two halves - the dispatch submits the right run, and the cleanup it runs
is idempotent and re-checks a shared collection name before dropping it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.worker.tasks import teardown_tasks
from app.worker.tasks.teardown_tasks import (
    dispatch_org_purge_cleanup,
    org_purge_cleanup_flow,
    purge_org_external_state,
)

pytestmark = pytest.mark.anyio


class TestDispatch:
    async def test_it_submits_the_cleanup_as_its_own_deployment_run(self) -> None:
        """`run_deployment` records the run on the Prefect server; that is what
        makes the cleanup outlive the process that dispatched it."""
        run = AsyncMock()
        with patch.object(teardown_tasks, "run_deployment", run):
            await dispatch_org_purge_cleanup(["a/one.txt"], ["docs"])

        run.assert_awaited_once_with(
            name="org-purge-cleanup/org-purge-cleanup",
            parameters={"storage_paths": ["a/one.txt"], "collections": ["docs"]},
            timeout=0,
        )


@asynccontextmanager
async def _db_ctx() -> Any:
    yield MagicMock()


def _patch_cleanup(*, referenced: list[str]) -> Any:
    """Patch everything `purge_org_external_state` reaches, so the store and the
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
            result = await purge_org_external_state(["u/a.txt", "u/b.txt"], ["docs", "wiki"])

        assert storage.delete.await_count == 2
        assert store.delete_collection.await_count == 2
        assert result == {"unlinked": 2, "dropped": 2}
        engine.dispose.assert_awaited_once()

    async def test_it_leaves_a_table_a_base_still_references(self) -> None:
        """`collection_name` is not tenant-unique, so a name a second org has
        claimed since the purge must keep its table (#913)."""
        storage, store, _engine, patches = _patch_cleanup(referenced=["wiki"])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = await purge_org_external_state([], ["docs", "wiki"])

        store.delete_collection.assert_awaited_once_with("docs")
        assert result == {"unlinked": 0, "dropped": 1}

    async def test_a_failed_unlink_or_drop_does_not_abort_the_rest(self) -> None:
        """Best-effort: a file already gone or a table that never existed is not a
        reason to abandon the cleanup a retry would otherwise repeat."""
        storage, store, _engine, patches = _patch_cleanup(referenced=[])
        storage.delete = AsyncMock(side_effect=OSError("gone"))
        store.delete_collection = AsyncMock(side_effect=SQLAlchemyError("no such table"))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = await purge_org_external_state(["u/a.txt"], ["docs"])

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
            result = await purge_org_external_state(["u/a.txt"], [])

        make_engine.assert_not_called()
        assert result == {"unlinked": 1, "dropped": 0}


class TestTheFlow:
    async def test_it_runs_the_cleanup(self) -> None:
        """The `@flow` wrapper is thin: it carries the durability and delegates the
        work to `purge_org_external_state`."""
        impl = AsyncMock(return_value={"unlinked": 1, "dropped": 1})
        with patch.object(teardown_tasks, "purge_org_external_state", impl):
            result = await org_purge_cleanup_flow(["u/a.txt"], ["docs"])

        impl.assert_awaited_once_with(["u/a.txt"], ["docs"])
        assert result == {"unlinked": 1, "dropped": 1}
