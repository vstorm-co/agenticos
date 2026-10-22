"""Agent-generated media: storage, tenant isolation, the record, the quota and the sweep."""

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
    generated_media_quota_reached,
    generated_media_url,
    keep_generated_media,
    load_generated_media,
    open_generated_media,
    organization_directory,
    save_generated_media,
)
from app.worker.tasks import generated_media_tasks

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


class TestTheQuota:
    async def test_an_organization_under_its_quota_may_generate(
        self, generated_media_ledger: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ):
        organization_id = uuid4()
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1)
        generated_media_ledger.append(
            {"organization_id": organization_id, "size_bytes": 1024 * 1024 - 1}
        )

        assert not await generated_media_quota_reached(organization_id)

    async def test_an_organization_at_its_quota_may_not(
        self, generated_media_ledger: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ):
        organization_id = uuid4()
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1)
        generated_media_ledger.append(
            {"organization_id": organization_id, "size_bytes": 1024 * 1024}
        )

        assert await generated_media_quota_reached(organization_id)

    async def test_another_organizations_files_do_not_count(
        self, generated_media_ledger: list[dict[str, object]], monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 1)
        generated_media_ledger.append({"organization_id": uuid4(), "size_bytes": 10**9})

        assert not await generated_media_quota_reached(uuid4())

    async def test_a_quota_of_zero_is_no_quota_and_reads_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "GENERATED_MEDIA_QUOTA_MB", 0)
        monkeypatch.setattr(generated_media, "get_db_context", None)

        assert not await generated_media_quota_reached(uuid4())


def _row() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), organization_id=uuid4(), storage_path=f"generated_{uuid4()}/x_image.png"
    )


class TestForgettingAConversation:
    async def test_the_rows_go_and_the_paths_come_back_for_the_unlink(
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

        paths = await GeneratedMediaService(db).forget_conversations(
            organization_id, [conversation_id]
        )

        assert paths == ["generated_x/a_video.mp4"]
        deleted.assert_awaited_once_with(
            db, organization_id=organization_id, conversation_ids=[conversation_id]
        )


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
        monkeypatch.setattr(generated_media.generated_media_repo, "delete_by_ids", deleted)
        return deleted

    async def test_files_past_the_period_go_bytes_first_then_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 30)
        rows = [_row(), _row()]
        expired = AsyncMock(return_value=rows)
        deleted = self._repo(monkeypatch, expired)
        storage = self._storage(monkeypatch)
        db = MagicMock()

        removed = await GeneratedMediaService(db).sweep_expired(now=self.NOW)

        assert removed == 2
        assert expired.await_args is not None
        assert expired.await_args.kwargs["cutoff"] == self.NOW - timedelta(days=30)
        assert [call.args[0] for call in storage.delete.await_args_list] == [
            row.storage_path for row in rows
        ]
        deleted.assert_awaited_once_with(db, ids=[row.id for row in rows])

    async def test_a_file_the_store_would_not_delete_keeps_its_row_and_ends_the_sweep(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The next batch would read the same rows again; the next sweep retries."""
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 30)
        monkeypatch.setattr(generated_media, "SWEEP_BATCH", 2)
        stuck, fine = _row(), _row()
        expired = AsyncMock(return_value=[stuck, fine])
        deleted = self._repo(monkeypatch, expired)
        self._storage(monkeypatch, refuses=frozenset({stuck.storage_path}))

        removed = await GeneratedMediaService(MagicMock()).sweep_expired(now=self.NOW)

        assert removed == 1
        assert expired.await_count == 1
        assert deleted.await_args is not None
        assert deleted.await_args.kwargs["ids"] == [fine.id]

    async def test_a_full_batch_is_followed_by_another(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 30)
        monkeypatch.setattr(generated_media, "SWEEP_BATCH", 1)
        expired = AsyncMock(side_effect=[[_row()], []])
        self._repo(monkeypatch, expired)
        self._storage(monkeypatch)

        assert await GeneratedMediaService(MagicMock()).sweep_expired() == 1
        assert expired.await_count == 2

    async def test_a_backlog_is_worked_off_over_several_sweeps(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 30)
        monkeypatch.setattr(generated_media, "SWEEP_BATCH", 1)
        monkeypatch.setattr(generated_media, "SWEEP_MAX_BATCHES", 3)
        expired = AsyncMock(side_effect=lambda *_args, **_kwargs: [_row()])
        self._repo(monkeypatch, expired)
        self._storage(monkeypatch)

        assert await GeneratedMediaService(MagicMock()).sweep_expired(now=self.NOW) == 3
        assert expired.await_count == 3

    async def test_a_period_of_zero_keeps_everything(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "GENERATED_MEDIA_RETENTION_DAYS", 0)
        expired = AsyncMock()
        monkeypatch.setattr(generated_media.generated_media_repo, "expired", expired)

        assert await GeneratedMediaService(MagicMock()).sweep_expired(now=self.NOW) == 0
        expired.assert_not_awaited()

    async def test_the_worker_task_runs_the_sweep_in_a_session_of_its_own(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        sessions: list[MagicMock] = []

        @asynccontextmanager
        async def session() -> AsyncGenerator[MagicMock]:
            db = MagicMock()
            sessions.append(db)
            yield db

        monkeypatch.setattr(generated_media_tasks, "get_worker_db_context", session)
        monkeypatch.setattr(GeneratedMediaService, "sweep_expired", AsyncMock(side_effect=[3, 0]))

        assert await generated_media_tasks.sweep_generated_media() == 3
        assert await generated_media_tasks.sweep_generated_media() == 0
        assert len(sessions) == 2
