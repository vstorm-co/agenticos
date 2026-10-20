"""What an ingestion job that ended for good leaves behind, settled (Codex on #2248).

A child the memory watchdog stopped never reaches its handler's cleanup, so its
document read `processing` and its sync log `running` with nothing left to
finish them. The worker hands the ending to these.
"""

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker import handlers
from app.worker.jobs import (
    INGEST_DOCUMENT,
    SYNC_COLLECTION,
    SYNC_SOURCE,
    IngestDocument,
    SyncCollection,
    SyncConnectorSource,
)
from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio

MODULE = "app.worker.tasks.rag_tasks"


@asynccontextmanager
async def _db() -> Any:
    yield MagicMock()


def _document() -> IngestDocument:
    return IngestDocument(
        rag_document_id=uuid.uuid4(),
        collection_name="docs",
        filepath="media/rag/a.pdf",
        source_path="a.pdf",
        replace=False,
        attempt=2,
    )


async def test_a_lost_ingestion_fails_its_document_with_why() -> None:
    job = _document()
    with patch(f"{MODULE}._fail_document", new=AsyncMock()) as fail:
        await handlers.settle_ended(
            INGEST_DOCUMENT.kind, INGEST_DOCUMENT.dump(job), "stopped by the memory watchdog"
        )

    fail.assert_awaited_once_with(
        str(job.rag_document_id),
        error_message="Stopped before it finished: stopped by the memory watchdog",
        attempt=2,
    )


@pytest.mark.parametrize(("status", "closed"), [("running", True), ("completed", False)])
async def test_a_lost_collection_sync_closes_its_log_only_while_it_runs(
    status: str, closed: bool
) -> None:
    job = SyncCollection(
        sync_log_id=uuid.uuid4(),
        source="local",
        collection_name="docs",
        mode="full",
        path="/d",
        knowledge_base_id=None,
    )
    with (
        patch(f"{MODULE}.get_worker_db_context", _db),
        patch(
            f"{MODULE}.sync_log_repo.get_by_id",
            new=AsyncMock(return_value=MagicMock(status=status)),
        ),
        patch(f"{MODULE}._update_sync_log", new=AsyncMock()) as close,
    ):
        await handlers.settle_ended(SYNC_COLLECTION.kind, SYNC_COLLECTION.dump(job), "killed")

    assert close.await_count == int(closed)
    if closed:
        assert close.await_args.kwargs == {"error_message": "Stopped before it finished: killed"}


async def test_a_lost_collection_sync_whose_log_is_gone_closes_nothing() -> None:
    job = SyncCollection(
        sync_log_id=uuid.uuid4(),
        source="local",
        collection_name="docs",
        mode="full",
        path="/d",
        knowledge_base_id=None,
    )
    with (
        patch(f"{MODULE}.get_worker_db_context", _db),
        patch(f"{MODULE}.sync_log_repo.get_by_id", new=AsyncMock(return_value=None)),
        patch(f"{MODULE}._update_sync_log", new=AsyncMock()) as close,
    ):
        await rag_tasks.settle_lost_collection_sync(job, "killed")

    close.assert_not_awaited()


async def test_a_lost_source_sync_marks_the_source_and_closes_the_log_it_was_queued_with() -> None:
    """Its own log, by id - never the source's newest running one, which can be a
    manual sync queued behind it (Codex, #2248)."""
    log_id = uuid.uuid4()
    job = SyncConnectorSource(source_id=uuid.uuid4(), sync_log_id=log_id)
    sources = MagicMock(update_after_sync=AsyncMock())
    with (
        patch(f"{MODULE}.get_worker_db_context", _db),
        patch(f"{MODULE}.SyncSourceService", return_value=sources),
        patch(f"{MODULE}._close_running_log", new=AsyncMock()) as close,
    ):
        await handlers.settle_ended(SYNC_SOURCE.kind, SYNC_SOURCE.dump(job), "killed")

    sources.update_after_sync.assert_awaited_once_with(
        str(job.source_id), "error", "Stopped before it finished: killed"
    )
    close.assert_awaited_once_with(str(log_id), "killed")


async def test_a_sync_queued_without_a_log_marks_the_source_and_closes_none() -> None:
    """A source with no collection when it came due is queued without a log."""
    job = SyncConnectorSource(source_id=uuid.uuid4(), sync_log_id=None)
    with (
        patch(f"{MODULE}.get_worker_db_context", _db),
        patch(f"{MODULE}.SyncSourceService", return_value=MagicMock(update_after_sync=AsyncMock())),
        patch(f"{MODULE}._close_running_log", new=AsyncMock()) as close,
    ):
        await rag_tasks.settle_lost_source_sync(job, "killed")

    close.assert_not_awaited()


async def test_a_kind_that_leaves_nothing_behind_settles_nothing() -> None:
    await handlers.settle_ended("expire-approvals", {}, "dead")


@pytest.mark.parametrize(("attempt", "closed"), [(1, False), (2, True)])
async def test_a_failed_collection_sync_closes_its_log_only_on_the_last_attempt(
    attempt: int, closed: bool
) -> None:
    from app.worker.attempt import Attempt, running

    job = SyncCollection(
        sync_log_id=uuid.uuid4(),
        source="local",
        collection_name="docs",
        mode="full",
        path="/d",
        knowledge_base_id=None,
    )
    with (
        patch(f"{MODULE}._run_sync", new=AsyncMock(side_effect=RuntimeError("disk full"))),
        patch(f"{MODULE}._update_sync_log", new=AsyncMock()) as close,
        running(Attempt(attempt, 2)),
        pytest.raises(RuntimeError),
    ):
        await rag_tasks.sync_collection(job)

    assert close.await_count == int(closed)
