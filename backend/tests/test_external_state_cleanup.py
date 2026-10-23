"""External-state cleanup survives the process that asked for it (#1274, #1349, #2219).

A committed delete - an organization purge (`OrganizationService.purge`) or a RAG
collection drop (`KnowledgeBaseService.delete`, `RAGDocumentService`) - leaves an
external cleanup behind: unlinking stored uploads and dropping vector tables. It is
queued as a job in the delete's own transaction, so it exists exactly when the
delete does and a worker retries it. These pin the two halves - the right jobs are
queued, and the cleanup they run is idempotent and re-checks a shared collection
name before dropping it.
"""

from contextlib import ExitStack, asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.worker.jobs import CLEANUP_EXTERNAL_STATE, CleanupExternalState, Restamp
from app.worker.tasks import teardown_tasks
from app.worker.tasks.teardown_tasks import (
    cleanup_external_state,
    queue_external_state_cleanup,
    run_external_state_cleanup,
    sweep_teardown_reservations,
)

pytestmark = pytest.mark.anyio


_ORG = UUID("11111111-1111-1111-1111-111111111111")
_KB = UUID("22222222-2222-2222-2222-222222222222")


def _restamp(collection: str = "handbook") -> Restamp:
    return Restamp(collection=collection, organization_id=_ORG, knowledge_base_id=_KB)


class TestQueueing:
    async def _queued(self, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        calls: list[tuple[Any, ...]] = []

        async def enqueue(db, task, payload, **options):
            calls.append((db, task, payload, options))

        db = MagicMock()
        with patch.object(teardown_tasks, "enqueue", enqueue):
            await queue_external_state_cleanup(db, *args, **kwargs)
        assert all(call[0] is db for call in calls), "every job rides the delete's own session"
        assert all(call[1] is CLEANUP_EXTERNAL_STATE for call in calls)
        return calls

    async def test_it_queues_one_cleanup_carrying_the_paths_and_the_drops(self) -> None:
        [(_, _, payload, options)] = await self._queued(
            ["a/one.txt"], ["docs"], organization_id=_ORG
        )
        assert payload == CleanupExternalState(
            storage_paths=["a/one.txt"], collections=["docs"], restamps=[]
        )
        assert options == {"organization_id": _ORG}

    async def test_a_purge_with_no_paths_still_queues_the_table_drops(self) -> None:
        [(_, _, payload, _)] = await self._queued([], ["docs"])
        assert payload.collections == ["docs"]

    async def test_it_chunks_a_large_path_list_and_drops_on_the_first_job_only(self) -> None:
        """Each job's row stays small, and a retry re-attempts one chunk (#1274)."""
        paths = [f"u/{i}.txt" for i in range(teardown_tasks._MAX_PATHS_PER_JOB + 1)]
        first, second = (call[2] for call in await self._queued(paths, ["docs"]))
        assert len(first.storage_paths) == teardown_tasks._MAX_PATHS_PER_JOB
        assert first.collections == ["docs"]
        assert (second.storage_paths, second.collections) == ([paths[-1]], [])

    async def test_restamps_are_chunked_on_their_own_and_zipped_onto_the_jobs(self) -> None:
        """More orphaned personal bases than a job carries spread across jobs, the way
        storage paths are (#1684)."""
        restamps = [_restamp(f"kb-{i}") for i in range(teardown_tasks._MAX_RESTAMPS_PER_JOB + 1)]
        first, second = (call[2] for call in await self._queued([], [], restamps))
        assert len(first.restamps) == teardown_tasks._MAX_RESTAMPS_PER_JOB
        assert second.restamps == [restamps[-1]]

    async def test_prefixes_ride_the_first_job_only(self) -> None:
        """An organization's generated media goes by prefix, in the purge's own
        transaction, rather than in a task the commit could outlive (#2310)."""
        paths = [f"u/{i}.txt" for i in range(teardown_tasks._MAX_PATHS_PER_JOB + 1)]
        first, second = (
            call[2] for call in await self._queued(paths, [], prefixes=["generated_org"])
        )
        assert (first.prefixes, second.prefixes) == (["generated_org"], [])

    async def test_a_job_queued_before_prefixes_existed_still_parses(self) -> None:
        payload = CleanupExternalState.model_validate(
            {"storage_paths": ["u/a.txt"], "collections": [], "restamps": []}
        )
        assert payload.prefixes == []

    async def test_a_job_with_no_prefixes_is_one_a_previous_worker_still_parses(self) -> None:
        """A worker from the release before prefixes forbids extra fields and fails a
        payload it cannot parse permanently - so an empty list stays out of the dump,
        and only a purge's prefixes need the current worker (#2310)."""
        from pydantic import BaseModel, ConfigDict

        class _PreviousRestamp(BaseModel):
            model_config = ConfigDict(frozen=True, extra="forbid")
            collection: str
            organization_id: UUID
            knowledge_base_id: UUID

        class _PreviousCleanup(BaseModel):
            model_config = ConfigDict(frozen=True, extra="forbid")
            storage_paths: list[str]
            collections: list[str]
            restamps: list[_PreviousRestamp]

        dumped = CLEANUP_EXTERNAL_STATE.dump(
            CleanupExternalState(storage_paths=["u/a.txt"], collections=[], restamps=[_restamp()])
        )
        assert "prefixes" not in dumped
        assert "required_paths" not in dumped
        _PreviousCleanup.model_validate(dumped)

        with_prefix = CLEANUP_EXTERNAL_STATE.dump(
            CleanupExternalState(
                storage_paths=[], collections=[], restamps=[], prefixes=["generated_org"]
            )
        )
        assert with_prefix["prefixes"] == ["generated_org"]
        assert CLEANUP_EXTERNAL_STATE.load(with_prefix).prefixes == ["generated_org"]

    async def test_required_paths_are_chunked_like_paths_and_kept_apart_from_them(self) -> None:
        """A deleted conversation's generated media rides its own field, whose
        failures fail the job (#2310)."""
        required = [f"generated_o/{i}.png" for i in range(teardown_tasks._MAX_PATHS_PER_JOB + 1)]
        first, second = (
            call[2] for call in await self._queued(["u/a.txt"], [], required_paths=required)
        )
        assert first.storage_paths == ["u/a.txt"]
        assert len(first.required_paths) == teardown_tasks._MAX_PATHS_PER_JOB
        assert (second.storage_paths, second.required_paths) == ([], [required[-1]])

    async def test_required_paths_are_dumped_only_when_there_are_some(self) -> None:
        dumped = CLEANUP_EXTERNAL_STATE.dump(
            CleanupExternalState(
                storage_paths=[], collections=[], restamps=[], required_paths=["generated_o/a.png"]
            )
        )
        assert dumped["required_paths"] == ["generated_o/a.png"]
        assert CLEANUP_EXTERNAL_STATE.load(dumped).required_paths == ["generated_o/a.png"]
        assert (
            CleanupExternalState.model_validate(
                {"storage_paths": [], "collections": [], "restamps": []}
            ).required_paths
            == []
        )


@asynccontextmanager
async def _db_ctx() -> Any:
    yield MagicMock(execute=AsyncMock())


def _patch_cleanup() -> Any:
    """Patch everything `cleanup_external_state` reaches - the store and the
    reservation release - so the drops are controllable. It no longer re-checks the
    knowledge-base table: the delete path already decided each name should be dropped
    and reserved it, so the cleanup drops unconditionally, then releases the name's
    reservation (#1362)."""
    storage = MagicMock(delete=AsyncMock())
    store = MagicMock(delete_collection=AsyncMock(), restamp_documents_to_untagged=AsyncMock())
    engine = MagicMock(dispose=AsyncMock())
    release = AsyncMock()

    patches = [
        patch("app.services.file_storage.get_file_storage", return_value=storage),
        patch.object(teardown_tasks, "create_async_engine", return_value=engine),
        patch("app.services.rag.vectorstore.PgVectorStore", return_value=store),
        patch("app.services.rag.embeddings.EmbeddingService", return_value=MagicMock()),
        patch("app.db.session.get_worker_db_context", _db_ctx),
        patch("app.repositories.collection_teardown_repo.release", release),
    ]
    return storage, store, engine, release, patches


class TestTheCleanup:
    async def test_it_unlinks_every_file_and_drops_and_releases_every_table(self) -> None:
        storage, store, engine, release, patches = _patch_cleanup()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = await cleanup_external_state(["u/a.txt", "u/b.txt"], ["docs", "wiki"])

        assert storage.delete.await_count == 2
        assert store.delete_collection.await_count == 2
        assert [call.args[1] for call in release.await_args_list] == ["docs", "wiki"]
        assert result == {"unlinked": 2, "dropped": 2, "restamped": 0}
        engine.dispose.assert_awaited_once()

    async def test_a_failed_drop_leaves_the_reservation_for_a_retry(self) -> None:
        """The name stays reserved when the drop fails: the table may still hold data,
        so freeing the name would let a claim adopt it. A retry drops and releases it
        (#1362)."""
        _storage, store, _engine, release, patches = _patch_cleanup()
        store.delete_collection = AsyncMock(side_effect=SQLAlchemyError("blip"))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = await cleanup_external_state([], ["docs"])

        release.assert_not_awaited()
        assert result == {"unlinked": 0, "dropped": 0, "restamped": 0}

    async def test_a_failed_unlink_does_not_abort_the_rest(self) -> None:
        """Best-effort: a file already gone is not a reason to abandon the cleanup."""
        storage, _store, _engine, _release, patches = _patch_cleanup()
        storage.delete = AsyncMock(side_effect=OSError("gone"))
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = await cleanup_external_state(["u/a.txt"], ["docs"])

        assert result == {"unlinked": 1, "dropped": 1, "restamped": 0}

    async def test_no_collections_touches_no_store(self) -> None:
        """A purge that only left files behind builds no vector-store engine."""
        storage, _store, _engine, _release, patches = _patch_cleanup()
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
        assert result == {"unlinked": 1, "dropped": 0, "restamped": 0}

    async def test_it_locks_and_releases_each_collection_it_drops(self) -> None:
        """The drop takes the advisory lock it shares with the claim path (#1355), and
        releases the name's reservation only after the table is gone (#1362)."""
        from app.db.locks import LockScope

        _storage, _store, _engine, release, patches = _patch_cleanup()
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
        assert [call.args[1] for call in release.await_args_list] == ["docs", "wiki"]

    async def test_a_legacy_run_without_a_reservation_skips_a_reclaimed_name(self) -> None:
        """A run queued before #1362 carries no reservation; if the name was reclaimed
        since, it falls back to the reference check and does not drop the new tenant's
        table - the safety an upgrade replaying an old run needs (#1362 review)."""
        _storage, store, _engine, release, patches = _patch_cleanup()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patch(
                "app.repositories.collection_teardown_repo.is_reserved",
                AsyncMock(return_value=False),
            ),
            patch(
                "app.repositories.knowledge_base_repo.list_by_collection_name",
                AsyncMock(return_value=[MagicMock()]),
            ),
        ):
            result = await cleanup_external_state([], ["docs"])

        store.delete_collection.assert_not_awaited()
        release.assert_not_awaited()
        assert result == {"unlinked": 0, "dropped": 0, "restamped": 0}

    async def test_it_untags_each_orphaned_personal_bases_own_documents(self) -> None:
        """A purge orphans a personal base by nulling its org; the cleanup hands the
        store that base's id and tenant, and the store untags exactly that base's own
        surviving rows so its new `vector_tenant=None` reaches them again (#1684)."""
        _storage, store, _engine, _release, patches = _patch_cleanup()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = await cleanup_external_state([], [], [_restamp()])

        store.restamp_documents_to_untagged.assert_awaited_once_with("handbook", _ORG, _KB)
        assert result == {"unlinked": 0, "dropped": 0, "restamped": 1}

    async def test_a_failed_restamp_attempts_the_rest_then_fails_the_flow(self) -> None:
        """A re-stamp has no sweep to reattempt it, so a failure is isolated per entry
        - the others still run - but then raised, failing the job so its retries
        re-run the idempotent cleanup rather than leaving a base stranded (#1684)."""
        from app.core.exceptions import DatabaseError

        _storage, store, _engine, _release, patches = _patch_cleanup()
        store.restamp_documents_to_untagged = AsyncMock(side_effect=[SQLAlchemyError("blip"), None])
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            pytest.raises(DatabaseError) as excinfo,
        ):
            await cleanup_external_state([], [], [_restamp("bad"), _restamp("good")])

        assert store.restamp_documents_to_untagged.await_count == 2
        assert excinfo.value.details == {"collections": ["bad"]}

    async def test_restamps_alone_still_build_the_store(self) -> None:
        """A purge that only orphaned a personal base - no files, no drops - still
        opens the vector store to untag it."""
        _storage, store, engine, _release, patches = _patch_cleanup()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            await cleanup_external_state([], [], [_restamp()])

        store.restamp_documents_to_untagged.assert_awaited_once()
        engine.dispose.assert_awaited_once()


class TestPrefixes:
    async def test_each_prefix_is_removed_whole_without_a_vector_store(self) -> None:
        storage, _store, _engine, _release, patches = _patch_cleanup()
        storage.delete_prefix = AsyncMock(return_value=3)
        with (
            patches[0],
            patch.object(teardown_tasks, "create_async_engine") as make_engine,
            patches[4],
        ):
            result = await cleanup_external_state([], [], [], ["generated_a", "generated_b"])

        assert [call.args[0] for call in storage.delete_prefix.await_args_list] == [
            "generated_a",
            "generated_b",
        ]
        make_engine.assert_not_called()
        assert result == {"unlinked": 0, "dropped": 0, "restamped": 0}

    async def test_a_prefix_the_store_refuses_fails_the_job_after_the_rest(self) -> None:
        """Its rows are gone, so the job's retries are the only thing that will ever
        try again - raised, after every other prefix and file was attempted."""
        from app.core.exceptions import ExternalServiceError

        storage, _store, _engine, _release, patches = _patch_cleanup()
        storage.delete_prefix = AsyncMock(side_effect=[OSError("denied"), 1])
        with patches[0], patches[4], pytest.raises(ExternalServiceError) as failed:
            await cleanup_external_state(["u/a.txt"], [], [], ["generated_a", "generated_b"])

        assert failed.value.details == {"prefixes": ["generated_a"], "storage_paths": []}
        assert storage.delete_prefix.await_count == 2
        storage.delete.assert_awaited_once_with("u/a.txt")


class TestRequiredPaths:
    async def test_a_required_path_the_store_refuses_fails_the_job_after_the_rest(self) -> None:
        """Its row went with the delete that queued it, so the job's retries are
        the only thing that will try it again (#2310) - unlike a plain path,
        whose failure is only logged."""
        from app.core.exceptions import ExternalServiceError

        storage, _store, _engine, _release, patches = _patch_cleanup()

        async def delete(path: str) -> None:
            if path in {"u/plain.txt", "generated_o/a.png"}:
                raise OSError("denied")

        storage.delete = AsyncMock(side_effect=delete)
        with patches[0], patches[4], pytest.raises(ExternalServiceError) as failed:
            await cleanup_external_state(
                ["u/plain.txt"],
                [],
                [],
                [],
                ["generated_o/a.png", "generated_o/b.png"],
            )

        assert failed.value.details == {"prefixes": [], "storage_paths": ["generated_o/a.png"]}
        assert [call.args[0] for call in storage.delete.await_args_list] == [
            "u/plain.txt",
            "generated_o/a.png",
            "generated_o/b.png",
        ]

    async def test_required_paths_that_all_go_complete_the_job(self) -> None:
        storage, _store, _engine, _release, patches = _patch_cleanup()
        with patches[0], patches[4]:
            result = await cleanup_external_state([], [], [], [], ["generated_o/a.png"])

        storage.delete.assert_awaited_once_with("generated_o/a.png")
        assert result == {"unlinked": 1, "dropped": 0, "restamped": 0}


class TestTheJob:
    async def test_it_runs_the_cleanup_with_what_the_job_carries(self) -> None:
        impl = AsyncMock(return_value={"unlinked": 1, "dropped": 1, "restamped": 1})
        job = CleanupExternalState(
            storage_paths=["u/a.txt"], collections=["docs"], restamps=[_restamp()]
        )
        with patch.object(teardown_tasks, "cleanup_external_state", impl):
            result = await run_external_state_cleanup(job)

        impl.assert_awaited_once_with(["u/a.txt"], ["docs"], [_restamp()], [], [])
        assert result == {"unlinked": 1, "dropped": 1, "restamped": 1}


def _patch_sweep(stale: list[Any], *, reserved: bool = True) -> Any:
    """Patch what `sweep_teardown_reservations` reaches - the stale scan, the still-
    reserved re-check, and everything `_drop_then_release`/`_vector_store` touch."""
    _storage, store, engine, release, patches = _patch_cleanup()
    scan = patches[1:]  # drop the file-storage patch; the sweep touches no files
    scan += [
        patch(
            "app.repositories.collection_teardown_repo.list_stale",
            AsyncMock(return_value=stale),
        ),
        patch(
            "app.repositories.collection_teardown_repo.is_reserved",
            AsyncMock(return_value=reserved),
        ),
    ]
    return store, engine, release, scan


class TestTheSweep:
    async def test_it_drops_and_releases_every_stale_reservation(self) -> None:
        stale = [MagicMock(collection_name="docs"), MagicMock(collection_name="wiki")]
        store, engine, release, scan = _patch_sweep(stale)
        with ExitStack() as stack:
            for p in scan:
                stack.enter_context(p)
            result = await sweep_teardown_reservations()

        assert store.delete_collection.await_count == 2
        assert [call.args[1] for call in release.await_args_list] == ["docs", "wiki"]
        assert result == {"swept": 2, "dropped": 2}
        engine.dispose.assert_awaited_once()

    async def test_a_reservation_finished_since_the_scan_is_skipped(self) -> None:
        """A normal cleanup, or an earlier sweep, may have dropped and released the
        name between the scan and the lock; the re-check under the lock skips it."""
        store, _engine, release, scan = _patch_sweep(
            [MagicMock(collection_name="docs")], reserved=False
        )
        with ExitStack() as stack:
            for p in scan:
                stack.enter_context(p)
            result = await sweep_teardown_reservations()

        store.delete_collection.assert_not_awaited()
        release.assert_not_awaited()
        assert result == {"swept": 1, "dropped": 0}

    async def test_a_failed_drop_leaves_the_reservation_for_the_next_sweep(self) -> None:
        store, _engine, release, scan = _patch_sweep([MagicMock(collection_name="docs")])
        store.delete_collection = AsyncMock(side_effect=SQLAlchemyError("blip"))
        with ExitStack() as stack:
            for p in scan:
                stack.enter_context(p)
            result = await sweep_teardown_reservations()

        release.assert_not_awaited()
        assert result == {"swept": 1, "dropped": 0}

    async def test_a_reservation_that_cannot_be_dropped_does_not_abort_the_sweep(self) -> None:
        """A legacy name current validation rejects raises from `_table` - a
        `BadRequestError`, not the `SQLAlchemyError` the drop catches - which must not
        disable the whole sweep: the row is isolated and the rest still run (#1364)."""
        from app.core.exceptions import BadRequestError

        store, _engine, release, scan = _patch_sweep(
            [MagicMock(collection_name="bad"), MagicMock(collection_name="docs")]
        )
        store.delete_collection = AsyncMock(side_effect=[BadRequestError(message="bad"), None])
        with ExitStack() as stack:
            for p in scan:
                stack.enter_context(p)
            result = await sweep_teardown_reservations()

        assert store.delete_collection.await_count == 2  # carried on past the bad one
        assert [call.args[1] for call in release.await_args_list] == ["docs"]
        assert result == {"swept": 2, "dropped": 1}

    async def test_no_stale_reservations_builds_no_store(self) -> None:
        """The common tick returns no rows, so it never builds a vector-store engine."""
        _store, _engine, _release, scan = _patch_sweep([])
        with (
            patch.object(teardown_tasks, "create_async_engine") as make_engine,
            ExitStack() as stack,
        ):
            for p in scan[1:]:  # keep our own create_async_engine assertion patch
                stack.enter_context(p)
            result = await sweep_teardown_reservations()

        make_engine.assert_not_called()
        assert result == {"swept": 0, "dropped": 0}
