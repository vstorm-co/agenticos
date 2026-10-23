"""Agent-generated media: storage, tenant isolation, the record, the quota and the sweep."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.services import generated_media
from app.services.generated_media import (
    GeneratedMediaService,
    StoredGeneratedMedia,
    admit_generated_media,
    generated_media_url,
    keep_generated_media,
    load_generated_media,
    open_generated_media,
    organization_directory,
    release_generated_media,
    save_generated_media,
    sweep_expired_generated_media,
)
from app.worker.tasks import generated_media_tasks, teardown_tasks

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _media_dir(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Point the file store at a throwaway directory for the test."""
    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)


async def test_a_saved_image_reads_back_byte_for_byte():
    organization_id = uuid4()
    filename = await save_generated_media(organization_id, b"\x89PNG-bytes", filename="image.png")

    assert filename.endswith("_image.png")
    assert await load_generated_media(organization_id, filename) == b"\x89PNG-bytes"


async def test_another_organization_cannot_read_the_image():
    """Storage is per-organization: the directory is built from the reader's id."""
    owner, intruder = uuid4(), uuid4()
    filename = await save_generated_media(owner, b"private", filename="image.png")

    with pytest.raises(NotFoundError):
        await load_generated_media(intruder, filename)


async def test_a_missing_image_is_not_found():
    with pytest.raises(NotFoundError):
        await load_generated_media(uuid4(), "deadbeef1234_image.png")


async def test_a_traversing_filename_cannot_climb_out_of_the_org_directory():
    """`../` in a name would resolve inside the shared root, into a sibling org."""
    owner, other = uuid4(), uuid4()
    leaf = await save_generated_media(other, b"someone-elses", filename="image.png")

    with pytest.raises(NotFoundError):
        await load_generated_media(owner, f"../generated_{other}/{leaf}")


async def test_the_serving_url_addresses_the_leaf():
    assert generated_media_url("abc123_image.png") == "/api/v1/generated/abc123_image.png"


async def test_a_file_is_found_and_measured_without_being_read():
    organization_id = uuid4()
    filename = await save_generated_media(organization_id, b"0123456789", filename="video.mp4")

    stored = await open_generated_media(organization_id, filename)

    assert stored == StoredGeneratedMedia(
        storage_path=f"{organization_directory(organization_id)}/{filename}", size=10
    )


@pytest.mark.parametrize("leaf", ["deadbeef1234_video.mp4", "../x", "a\\b", "", ".", ".."])
async def test_a_name_that_is_not_one_of_this_organizations_files_is_not_found(leaf: str):
    with pytest.raises(NotFoundError):
        await open_generated_media(uuid4(), leaf)


async def test_another_organization_cannot_open_the_file():
    filename = await save_generated_media(uuid4(), b"private", filename="video.mp4")

    with pytest.raises(NotFoundError):
        await open_generated_media(uuid4(), filename)


class TestKeeping:
    """What an agent's tool stores is recorded, so it is counted and expires (#2310)."""

    async def test_a_kept_file_is_stored_and_recorded_with_its_conversation(
        self, generated_media_ledger: list[dict[str, object]]
    ):
        organization_id, conversation_id = uuid4(), uuid4()

        leaf = await keep_generated_media(
            organization_id, b"clip", filename="video.mp4", conversation_id=conversation_id
        )

        assert await load_generated_media(organization_id, leaf) == b"clip"
        assert generated_media_ledger == [
            {
                "organization_id": organization_id,
                "conversation_id": conversation_id,
                "filename": leaf,
                "storage_path": f"generated_{organization_id}/{leaf}",
                "size_bytes": 4,
            }
        ]

    async def test_a_file_that_cannot_be_recorded_is_not_kept(
        self, generated_media_ledger: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ):
        """Bytes with no row are counted by nothing and swept by nothing."""
        organization_id = uuid4()
        monkeypatch.setattr(
            generated_media.generated_media_repo,
            "create",
            AsyncMock(side_effect=RuntimeError("database gone")),
        )

        with pytest.raises(RuntimeError, match="database gone"):
            await keep_generated_media(
                organization_id, b"clip", filename="video.mp4", conversation_id=None
            )

        directory = settings.MEDIA_DIR / organization_directory(organization_id)
        assert list(directory.iterdir()) == []

    async def test_a_call_cancelled_before_its_record_does_not_keep_the_file(
        self, generated_media_ledger: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ):
        """Stop, or a run timing out, cancels the tool call; `CancelledError` is not
        an `Exception`, and the file it would leave is just as unrecorded."""
        organization_id = uuid4()
        monkeypatch.setattr(
            generated_media.generated_media_repo,
            "create",
            AsyncMock(side_effect=asyncio.CancelledError()),
        )

        with pytest.raises(asyncio.CancelledError):
            await keep_generated_media(
                organization_id, b"clip", filename="video.mp4", conversation_id=uuid4()
            )

        directory = settings.MEDIA_DIR / organization_directory(organization_id)
        assert list(directory.iterdir()) == []

    async def test_a_failed_unlink_does_not_replace_the_cancellation(
        self,
        generated_media_ledger: list[dict[str, object]],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        """Raised from the cleanup, the store's error would turn a Stop into a
        failure and the cancellation would never reach the run."""
        monkeypatch.setattr(
            generated_media.generated_media_repo,
            "create",
            AsyncMock(side_effect=asyncio.CancelledError()),
        )
        storage = MagicMock()
        storage.save = AsyncMock(return_value="generated_x/a_video.mp4")
        storage.delete = AsyncMock(side_effect=OSError("store refused"))
        monkeypatch.setattr(generated_media, "get_file_storage", lambda: storage)

        with pytest.raises(asyncio.CancelledError):
            await keep_generated_media(
                uuid4(), b"clip", filename="video.mp4", conversation_id=uuid4()
            )

        storage.delete.assert_awaited_once()
        assert "generated_media_not_unlinked" in [record.message for record in caplog.records]


MB = 1024 * 1024


class TestTheQuota:
    async def test_an_organization_under_its_quota_may_generate_and_holds_its_estimate(
        self,
        generated_media_ledger: list[dict[str, object]],
        generated_media_reservations: dict[object, dict[str, object]],
        monkeypatch: pytest.MonkeyPatch,
    ):
        organization_id = uuid4()
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 2)
        generated_media_ledger.append({"organization_id": organization_id, "size_bytes": MB})

        admission = await admit_generated_media(organization_id, estimate_bytes=MB)

        assert admission.admitted
        assert generated_media_reservations == {
            admission.reservation_id: {"organization_id": organization_id, "size_bytes": MB}
        }

    async def test_an_organization_at_its_quota_may_not(
        self,
        generated_media_ledger: list[dict[str, object]],
        generated_media_reservations: dict[object, dict[str, object]],
        monkeypatch: pytest.MonkeyPatch,
    ):
        organization_id = uuid4()
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1)
        generated_media_ledger.append({"organization_id": organization_id, "size_bytes": MB})

        admission = await admit_generated_media(organization_id, estimate_bytes=1)

        assert admission == generated_media.Admission(admitted=False)
        assert generated_media_reservations == {}

    async def test_a_call_whose_estimate_would_pass_the_quota_is_refused(
        self, generated_media_ledger: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ):
        organization_id = uuid4()
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1)
        generated_media_ledger.append({"organization_id": organization_id, "size_bytes": MB // 2})

        assert not (await admit_generated_media(organization_id, estimate_bytes=MB)).admitted

    async def test_calls_in_flight_count_against_the_next(
        self, generated_media_ledger: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ):
        organization_id = uuid4()
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1)

        first = await admit_generated_media(organization_id, estimate_bytes=MB // 2)
        second = await admit_generated_media(organization_id, estimate_bytes=MB // 2)
        third = await admit_generated_media(organization_id, estimate_bytes=1)

        assert (first.admitted, second.admitted, third.admitted) == (True, True, False)

    async def test_concurrent_calls_are_admitted_only_as_far_as_the_quota_goes(
        self,
        generated_media_ledger: list[dict[str, object]],
        generated_media_reservations: dict[object, dict[str, object]],
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Each call used to read the total in a transaction of its own and record
        its file minutes later, so every call started at once passed the same
        check (#2310). Reading the claims yields here, as a query does, so the
        calls interleave wherever nothing serializes them."""
        organization_id = uuid4()
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 2)
        bytes_reserved = generated_media.generated_media_repo.bytes_reserved

        async def slow_bytes_reserved(db: object, *, organization_id: object, since: object) -> int:
            reserved = await bytes_reserved(db, organization_id=organization_id, since=since)
            await asyncio.sleep(0)
            return reserved

        monkeypatch.setattr(
            generated_media.generated_media_repo, "bytes_reserved", slow_bytes_reserved
        )

        admissions = await asyncio.gather(
            *(admit_generated_media(organization_id, estimate_bytes=MB) for _ in range(5))
        )

        assert sum(admission.admitted for admission in admissions) == 2
        assert sum(int(str(c["size_bytes"])) for c in generated_media_reservations.values()) == (
            2 * MB
        )

    async def test_another_organizations_files_do_not_count(
        self, generated_media_ledger: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1)
        generated_media_ledger.append({"organization_id": uuid4(), "size_bytes": 10**9})

        assert (await admit_generated_media(uuid4(), estimate_bytes=1)).admitted

    async def test_stale_claims_are_not_counted(
        self, generated_media_ledger: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ):
        """A claim older than its lifetime belongs to a call that died; it is
        measured from the lifetime back from now."""
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1)
        reserved = AsyncMock(return_value=0)
        monkeypatch.setattr(generated_media.generated_media_repo, "bytes_reserved", reserved)
        before = datetime.now(UTC)

        await admit_generated_media(uuid4(), estimate_bytes=1)

        assert reserved.await_args is not None
        since = reserved.await_args.kwargs["since"]
        assert before - generated_media.RESERVATION_LIFETIME <= since <= datetime.now(UTC)

    async def test_a_quota_of_zero_is_no_quota_and_reads_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 0)
        monkeypatch.setattr(generated_media, "get_db_context", None)

        assert await admit_generated_media(uuid4(), estimate_bytes=10**12) == (
            generated_media.Admission(admitted=True)
        )


class TestTheReservation:
    """An admitted call's claim is replaced by its file, or given back."""

    async def test_keeping_the_file_replaces_the_claim_with_its_real_size(
        self,
        generated_media_ledger: list[dict[str, object]],
        generated_media_reservations: dict[object, dict[str, object]],
        monkeypatch: pytest.MonkeyPatch,
    ):
        organization_id = uuid4()
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1)
        admission = await admit_generated_media(organization_id, estimate_bytes=MB // 2)

        await keep_generated_media(
            organization_id,
            b"clip",
            filename="video.mp4",
            conversation_id=None,
            reservation_id=admission.reservation_id,
        )

        assert generated_media_reservations == {}
        assert [row["size_bytes"] for row in generated_media_ledger] == [4]

    async def test_a_file_that_cannot_be_recorded_leaves_the_claim_to_its_caller(
        self,
        generated_media_ledger: list[dict[str, object]],
        generated_media_reservations: dict[object, dict[str, object]],
        monkeypatch: pytest.MonkeyPatch,
    ):
        """The record and the release are one transaction: rolled back together,
        the claim is still there for the caller's release."""
        organization_id = uuid4()
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1)
        admission = await admit_generated_media(organization_id, estimate_bytes=MB // 2)
        monkeypatch.setattr(
            generated_media.generated_media_repo,
            "create",
            AsyncMock(side_effect=RuntimeError("database gone")),
        )

        with pytest.raises(RuntimeError):
            await keep_generated_media(
                organization_id,
                b"clip",
                filename="video.mp4",
                conversation_id=None,
                reservation_id=admission.reservation_id,
            )
        assert admission.reservation_id in generated_media_reservations

        assert admission.reservation_id is not None
        await release_generated_media(organization_id, admission.reservation_id)

        assert generated_media_reservations == {}

    async def test_a_release_that_fails_is_logged_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """The claim stops counting after its lifetime anyway; the error that
        ended the call is the one that goes on."""

        @asynccontextmanager
        async def broken() -> AsyncGenerator[MagicMock]:
            raise RuntimeError("database gone")
            yield MagicMock()  # pragma: no cover - never reached

        monkeypatch.setattr(generated_media, "get_db_context", broken)

        await release_generated_media(uuid4(), uuid4())

        assert "generated_media_reservation_not_released" in [r.message for r in caplog.records]


def _row(created_at: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        storage_path=f"generated_{uuid4()}/x_image.png",
        created_at=created_at or datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestForgetting:
    """The rows go in the delete's transaction; the bytes in a job queued in it."""

    @staticmethod
    def _queue(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
        queued = AsyncMock()
        monkeypatch.setattr(teardown_tasks, "queue_external_state_cleanup", queued)
        return queued

    async def test_a_conversations_rows_go_and_its_bytes_are_queued_for_the_unlink(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        organization_id, conversation_id = uuid4(), uuid4()
        db = MagicMock()
        monkeypatch.setattr(
            generated_media.generated_media_repo,
            "paths_in_conversations",
            AsyncMock(return_value=["generated_x/a_video.mp4"]),
        )
        deleted = AsyncMock(return_value=1)
        monkeypatch.setattr(
            generated_media.generated_media_repo, "delete_in_conversations", deleted
        )
        queued = self._queue(monkeypatch)

        await GeneratedMediaService(db).forget_conversations(organization_id, [conversation_id])

        deleted.assert_awaited_once_with(
            db, organization_id=organization_id, conversation_ids=[conversation_id]
        )
        queued.assert_awaited_once_with(
            db, [], [], required_paths=["generated_x/a_video.mp4"], organization_id=organization_id
        )

    async def test_a_conversation_that_generated_nothing_queues_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            generated_media.generated_media_repo,
            "paths_in_conversations",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            generated_media.generated_media_repo, "delete_in_conversations", AsyncMock()
        )
        queued = self._queue(monkeypatch)

        await GeneratedMediaService(MagicMock()).forget_conversations(uuid4(), [uuid4()])

        queued.assert_not_awaited()

    async def test_an_accounts_conversations_take_their_generated_media(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Account deletion: the cascade would leave the rows conversation-less and
        the bytes readable by the organization (#2310)."""
        user_id = uuid4()
        db = MagicMock()
        deleted = AsyncMock(return_value=["generated_a/x_image.png", "generated_b/y_speech.mp3"])
        monkeypatch.setattr(
            generated_media.generated_media_repo, "delete_in_conversations_of_user", deleted
        )
        queued = self._queue(monkeypatch)

        await GeneratedMediaService(db).forget_user(user_id)

        deleted.assert_awaited_once_with(db, user_id=user_id)
        queued.assert_awaited_once_with(
            db,
            [],
            [],
            required_paths=["generated_a/x_image.png", "generated_b/y_speech.mp3"],
            organization_id=None,
        )


class _Sessions:
    """A stand-in for `get_worker_db_context` that records how each session ended."""

    def __init__(self) -> None:
        self.ended: list[str] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[MagicMock]:
        try:
            yield MagicMock()
        except BaseException:
            self.ended.append("rollback")
            raise
        self.ended.append("commit")


class TestTheRetentionSweep:
    NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    @staticmethod
    def _storage(
        monkeypatch: pytest.MonkeyPatch, *, refuses: frozenset[str] = frozenset()
    ) -> MagicMock:
        storage = MagicMock()

        async def delete(path: str) -> None:
            if path in refuses:
                raise OSError("store refused")

        storage.delete = AsyncMock(side_effect=delete)
        monkeypatch.setattr(generated_media, "get_file_storage", lambda: storage)
        return storage

    @staticmethod
    def _repo(monkeypatch: pytest.MonkeyPatch, expired: AsyncMock) -> AsyncMock:
        """Stub the repository; the delete answers how many ids it was given."""

        async def delete_by_ids(_db: object, *, ids: list[object]) -> int:
            return len(ids)

        deleted = AsyncMock(side_effect=delete_by_ids)
        monkeypatch.setattr(generated_media.generated_media_repo, "expired", expired)
        monkeypatch.setattr(
            generated_media.generated_media_repo,
            "delete_stale_reservations",
            AsyncMock(return_value=0),
        )
        monkeypatch.setattr(generated_media.generated_media_repo, "delete_by_ids", deleted)
        return deleted

    @staticmethod
    def _sessions(monkeypatch: pytest.MonkeyPatch) -> _Sessions:
        sessions = _Sessions()
        monkeypatch.setattr(generated_media, "get_worker_db_context", sessions)
        return sessions

    async def test_files_past_the_period_go_bytes_first_then_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 30)
        rows = [_row(), _row()]
        expired = AsyncMock(return_value=rows)
        deleted = self._repo(monkeypatch, expired)
        storage = self._storage(monkeypatch)
        self._sessions(monkeypatch)

        removed = await sweep_expired_generated_media(now=self.NOW)

        assert removed == 2
        assert expired.await_args is not None
        assert expired.await_args.kwargs["cutoff"] == self.NOW - timedelta(days=30)
        assert expired.await_args.kwargs["unlinked_cutoff"] == self.NOW - timedelta(days=7)
        assert expired.await_args.kwargs["after"] is None
        assert [call.args[0] for call in storage.delete.await_args_list] == [
            row.storage_path for row in rows
        ]
        assert deleted.await_args is not None
        assert deleted.await_args.kwargs["ids"] == [row.id for row in rows]

    async def test_each_batch_commits_before_the_next_so_a_timeout_keeps_its_work(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """One transaction for the run let the job's timeout roll back every row
        whose bytes were already gone, and a backlog then never committed at all."""
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 30)
        monkeypatch.setattr(generated_media, "SWEEP_BATCH", 1)
        first = _row()
        expired = AsyncMock(side_effect=[[first], asyncio.CancelledError()])
        deleted = self._repo(monkeypatch, expired)
        self._storage(monkeypatch)
        sessions = self._sessions(monkeypatch)

        with pytest.raises(asyncio.CancelledError):
            await sweep_expired_generated_media(now=self.NOW)

        assert sessions.ended == ["commit", "commit", "rollback"]
        assert deleted.await_args_list[0].kwargs["ids"] == [first.id]

    async def test_a_stuck_file_keeps_its_row_and_the_sweep_reads_past_it(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """One undeletable oldest file used to end every run at its first batch."""
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 30)
        monkeypatch.setattr(generated_media, "SWEEP_BATCH", 2)
        stuck, fine = _row(datetime(2026, 1, 1, tzinfo=UTC)), _row(datetime(2026, 1, 2, tzinfo=UTC))
        later = _row(datetime(2026, 1, 3, tzinfo=UTC))
        expired = AsyncMock(side_effect=[[stuck, fine], [later]])
        deleted = self._repo(monkeypatch, expired)
        self._storage(monkeypatch, refuses=frozenset({stuck.storage_path}))
        self._sessions(monkeypatch)

        removed = await sweep_expired_generated_media(now=self.NOW)

        assert removed == 2
        assert expired.await_args_list[1].kwargs["after"] == (fine.created_at, fine.id)
        assert [call.kwargs["ids"] for call in deleted.await_args_list] == [[fine.id], [later.id]]

    async def test_a_whole_batch_of_stuck_files_does_not_stop_the_sweep(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A batch's worth of undeletable files used to stop retention for every
        organization; the next batch now starts after them."""
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 30)
        monkeypatch.setattr(generated_media, "SWEEP_BATCH", 2)
        stuck = [_row(), _row()]
        fine = _row()
        expired = AsyncMock(side_effect=[stuck, [fine]])
        self._repo(monkeypatch, expired)
        self._storage(monkeypatch, refuses=frozenset(row.storage_path for row in stuck))
        self._sessions(monkeypatch)

        assert await sweep_expired_generated_media(now=self.NOW) == 1
        assert expired.await_args_list[1].kwargs["after"] == (stuck[1].created_at, stuck[1].id)

    async def test_a_backlog_is_worked_off_over_several_sweeps(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 30)
        monkeypatch.setattr(generated_media, "SWEEP_BATCH", 1)
        monkeypatch.setattr(generated_media, "SWEEP_MAX_BATCHES", 3)
        expired = AsyncMock(side_effect=lambda *_args, **_kwargs: [_row()])
        self._repo(monkeypatch, expired)
        self._storage(monkeypatch)
        sessions = self._sessions(monkeypatch)

        assert await sweep_expired_generated_media(now=self.NOW) == 3
        assert expired.await_count == 3
        assert sessions.ended == ["commit"] * 4

    async def test_no_batch_starts_once_the_time_budget_is_spent(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The run ends between batches, under the job's timeout, not inside one."""
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 30)
        monkeypatch.setattr(generated_media, "SWEEP_BATCH", 1)
        monkeypatch.setattr(generated_media, "SWEEP_TIME_BUDGET", timedelta(0))
        expired = AsyncMock(side_effect=lambda *_args, **_kwargs: [_row()])
        self._repo(monkeypatch, expired)
        self._storage(monkeypatch)
        self._sessions(monkeypatch)

        assert await sweep_expired_generated_media() == 1
        assert expired.await_count == 1

    async def test_a_period_of_zero_still_bounds_files_with_no_conversation(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Retention off keeps every file made in a conversation; one made with
        none - a preview, a `/btw` aside, an API run with no thread - counts
        against the quota and nobody could free it, so it still goes after its
        short lifetime (#2310)."""
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 0)
        unlinked = _row()
        expired = AsyncMock(return_value=[unlinked])
        deleted = self._repo(monkeypatch, expired)
        self._storage(monkeypatch)
        self._sessions(monkeypatch)

        assert await sweep_expired_generated_media(now=self.NOW) == 1
        assert expired.await_args is not None
        assert expired.await_args.kwargs["cutoff"] is None
        assert expired.await_args.kwargs["unlinked_cutoff"] == (
            self.NOW - generated_media.UNLINKED_MEDIA_LIFETIME
        )
        assert deleted.await_args is not None
        assert deleted.await_args.kwargs["ids"] == [unlinked.id]

    async def test_claims_of_calls_that_died_go_before_the_files(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """A call whose process died never released its claim; past its lifetime
        it stops counting, and the sweep removes it."""
        expired = AsyncMock(return_value=[])
        self._repo(monkeypatch, expired)
        stale = AsyncMock(return_value=2)
        monkeypatch.setattr(
            generated_media.generated_media_repo, "delete_stale_reservations", stale
        )
        self._storage(monkeypatch)
        sessions = self._sessions(monkeypatch)

        assert await sweep_expired_generated_media(now=self.NOW) == 0

        assert stale.await_args is not None
        assert stale.await_args.kwargs["before"] == self.NOW - timedelta(hours=1)
        assert sessions.ended == ["commit", "commit"]
        assert "generated_media_reservations_expired" in [r.message for r in caplog.records]

    async def test_the_worker_task_runs_the_sweep_and_logs_what_went(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        monkeypatch.setattr(
            generated_media_tasks,
            "sweep_expired_generated_media",
            AsyncMock(side_effect=[3, 0]),
        )

        with caplog.at_level("INFO", logger=generated_media_tasks.__name__):
            assert await generated_media_tasks.sweep_generated_media() == 3
            assert await generated_media_tasks.sweep_generated_media() == 0

        assert [record.message for record in caplog.records] == ["generated_media_swept"]
