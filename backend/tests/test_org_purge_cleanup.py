"""The org-teardown cleanup survives the process that dispatched it.

`OrganizationService.purge` used to hand its external cleanup - unlinking stored
uploads, dropping vector tables - to an in-process `spawn_after_commit` task,
which died with the process. It now submits a durable Prefect deployment run: the
run is recorded on the server and retried by a worker (#1274).

What that left was the window before the submission. The intent is written in
the purge's own transaction now, so it commits with the delete, and a sweep
re-dispatches anything nothing finished - which is what the dispatch tests below
pin, along with the cleanup itself being idempotent and re-checking a shared
collection name before dropping it (#1269).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.worker.tasks import teardown_tasks
from app.worker.tasks.teardown_tasks import (
    dispatch_org_purge_cleanup,
    org_purge_cleanup_flow,
    purge_org_external_state,
    teardown_sweep_flow,
)

pytestmark = pytest.mark.anyio


class TestDispatch:
    @staticmethod
    def _session() -> Any:
        """A worker session context whose `db` is a mock, for the stamp below."""
        db = MagicMock()

        @asynccontextmanager
        async def ctx() -> Any:
            yield db

        return db, ctx

    async def test_it_submits_the_cleanup_as_its_own_deployment_run(self) -> None:
        """`run_deployment` records the run on the Prefect server; that is what
        makes the cleanup outlive the process that dispatched it."""
        intent_id = uuid4()
        run = AsyncMock()
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "run_deployment", run),
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(teardown_tasks.teardown_intent_repo, "mark_dispatched", AsyncMock()),
        ):
            await dispatch_org_purge_cleanup(intent_id)

        run.assert_awaited_once_with(
            name="org-purge-cleanup/org-purge-cleanup",
            parameters={"intent_id": str(intent_id)},
            timeout=0,
        )

    async def test_the_payload_is_an_id_rather_than_the_paths_themselves(self) -> None:
        """Which is what removed the chunking this used to do: a large org can
        leave tens of thousands of files behind, and the whole payload had to
        stay under Prefect's 512 KiB flow-parameter limit. The flow reads them
        from the row (#1269)."""
        run = AsyncMock()
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "run_deployment", run),
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(teardown_tasks.teardown_intent_repo, "mark_dispatched", AsyncMock()),
        ):
            await dispatch_org_purge_cleanup(uuid4())

        assert set(run.await_args.kwargs["parameters"]) == {"intent_id"}

    async def test_a_dispatched_intent_is_stamped_so_the_sweep_leaves_it_alone(self) -> None:
        intent_id = uuid4()
        stamp = AsyncMock()
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "run_deployment", AsyncMock()),
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(teardown_tasks.teardown_intent_repo, "mark_dispatched", stamp),
        ):
            await dispatch_org_purge_cleanup(intent_id)

        assert stamp.await_args.args[1] == intent_id

    async def test_a_transient_submission_failure_is_retried(self) -> None:
        run = AsyncMock(side_effect=[RuntimeError("prefect blip"), None])
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "run_deployment", run),
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(teardown_tasks.teardown_intent_repo, "mark_dispatched", AsyncMock()),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            await dispatch_org_purge_cleanup(uuid4())

        assert run.await_count == 2

    async def test_a_submission_that_keeps_failing_leaves_the_intent_for_the_sweep(self) -> None:
        """Not fatal any more, and that is the whole of #1269: the row stays
        undispatched, so the sweep finds it. Stamping it here would tell the
        sweep a run exists that does not."""
        run = AsyncMock(side_effect=RuntimeError("prefect down"))
        stamp = AsyncMock()
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "run_deployment", run),
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(teardown_tasks.teardown_intent_repo, "mark_dispatched", stamp),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            await dispatch_org_purge_cleanup(uuid4())

        assert run.await_count == teardown_tasks._SUBMIT_ATTEMPTS
        stamp.assert_not_awaited()


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
    @staticmethod
    def _session() -> Any:
        db = MagicMock(commit=AsyncMock())

        @asynccontextmanager
        async def ctx() -> Any:
            yield db

        return db, ctx

    async def test_it_reads_what_to_release_from_the_intent(self) -> None:
        """The parameters carry an id; the row carries the work."""
        intent = MagicMock(storage_paths=["u/a.txt"], collections=["docs"])
        impl = AsyncMock(return_value={"unlinked": 1, "dropped": 1})
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(
                teardown_tasks.teardown_intent_repo, "get", AsyncMock(return_value=intent)
            ),
            patch.object(teardown_tasks.teardown_intent_repo, "finish", AsyncMock()),
            patch.object(teardown_tasks, "purge_org_external_state", impl),
        ):
            result = await org_purge_cleanup_flow(str(uuid4()))

        impl.assert_awaited_once_with(["u/a.txt"], ["docs"])
        assert result == {"unlinked": 1, "dropped": 1}

    async def test_finishing_deletes_the_intent(self) -> None:
        """The row's absence is the completion, so nothing has to interpret a
        status column and no sweep has to decide what `done` means."""
        intent_id = uuid4()
        finish = AsyncMock()
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(
                teardown_tasks.teardown_intent_repo,
                "get",
                AsyncMock(return_value=MagicMock(storage_paths=[], collections=[])),
            ),
            patch.object(teardown_tasks.teardown_intent_repo, "finish", finish),
            patch.object(teardown_tasks, "purge_org_external_state", AsyncMock(return_value={})),
        ):
            await org_purge_cleanup_flow(str(intent_id))

        assert finish.await_args.args[1] == intent_id

    async def test_an_intent_already_gone_is_a_run_that_already_succeeded(self) -> None:
        """A duplicate submission, or a retry after the work landed. Nothing to
        do and nothing to complain about."""
        impl = AsyncMock()
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(teardown_tasks.teardown_intent_repo, "get", AsyncMock(return_value=None)),
            patch.object(teardown_tasks, "purge_org_external_state", impl),
        ):
            result = await org_purge_cleanup_flow(str(uuid4()))

        impl.assert_not_awaited()
        assert result == {"unlinked": 0, "dropped": 0}


class TestTheSweep:
    """The half `spawn_after_commit` cannot cover (#1269).

    A process that died between the purge's commit and the hand-off leaves an
    intent nobody ever submitted, and the committed delete has already removed
    the paths and collection names a retry would otherwise need to find.
    """

    @staticmethod
    def _session() -> Any:
        db = MagicMock(commit=AsyncMock())

        @asynccontextmanager
        async def ctx() -> Any:
            yield db

        return db, ctx

    async def test_it_re_dispatches_what_it_claims(self) -> None:
        first, second = MagicMock(id=uuid4()), MagicMock(id=uuid4())
        run = AsyncMock()
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(
                teardown_tasks.teardown_intent_repo,
                "claim_stale",
                AsyncMock(return_value=[first, second]),
            ),
            patch.object(teardown_tasks, "run_deployment", run),
        ):
            result = await teardown_sweep_flow()

        assert result == {"claimed": 2, "dispatched": 2}
        assert [call.kwargs["parameters"]["intent_id"] for call in run.await_args_list] == [
            str(first.id),
            str(second.id),
        ]

    async def test_a_quiet_fleet_dispatches_nothing(self) -> None:
        run = AsyncMock()
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(
                teardown_tasks.teardown_intent_repo, "claim_stale", AsyncMock(return_value=[])
            ),
            patch.object(teardown_tasks, "run_deployment", run),
        ):
            result = await teardown_sweep_flow()

        run.assert_not_awaited()
        assert result == {"claimed": 0, "dispatched": 0}

    async def test_one_submission_failing_does_not_abandon_the_others(self) -> None:
        first, second = MagicMock(id=uuid4()), MagicMock(id=uuid4())
        run = AsyncMock(side_effect=[RuntimeError("down")] * 3 + [None])
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(
                teardown_tasks.teardown_intent_repo,
                "claim_stale",
                AsyncMock(return_value=[first, second]),
            ),
            patch.object(teardown_tasks, "run_deployment", run),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            result = await teardown_sweep_flow()

        # The first exhausted its retries; the second went. It stays claimed
        # either way, and the next sweep past the stale window takes it again.
        assert result == {"claimed": 2, "dispatched": 1}

    async def test_it_asks_for_a_bounded_batch_past_a_generous_deadline(self) -> None:
        """A backlog drains over several ticks rather than in one burst, and the
        deadline sits well past the flow's own retries so a healthy run is never
        duplicated by impatience."""
        claim = AsyncMock(return_value=[])
        _db, ctx = self._session()
        with (
            patch.object(teardown_tasks, "get_worker_db_context", ctx),
            patch.object(teardown_tasks.teardown_intent_repo, "claim_stale", claim),
        ):
            await teardown_sweep_flow()

        assert claim.await_args.kwargs == {
            "older_than": teardown_tasks._STALE_AFTER,
            "limit": teardown_tasks._SWEEP_BATCH,
        }
        assert timedelta(minutes=3) < teardown_tasks._STALE_AFTER
