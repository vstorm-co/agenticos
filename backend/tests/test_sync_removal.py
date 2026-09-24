"""A connector sync removes what its source no longer lists (#984).

Before this a page taken down, a file deleted from a Drive folder or an object
removed from a bucket stayed searchable for good: `_run_source_sync` ingested
and updated and never removed. What is pinned here is when it removes - only
against a complete listing, only the source's own documents, vectors before
the row - and that the sync log says what it did and what it could not.

The store and the database are replaced; `IngestionService` stays real apart
from the vector delete, whose answer is what decides whether a row goes.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError
from app.services.rag.connectors import RemoteFile, RemoteListing, WithdrawnFile
from app.services.rag.models import IngestionStatus
from app.worker.tasks import rag_tasks

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("sole_source_run")]

SOURCE_ID = uuid.uuid4()
KEPT = RemoteFile(id="k", name="kept.md", source_path="web://docs.example.com/kept")
HIDDEN = RemoteFile(id="h", name="hidden.md", source_path="web://docs.example.com/hidden")


def _row(source_path: str, vector_document_id: str | None = "vec-gone") -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(), source_path=source_path, vector_document_id=vector_document_id
    )


def _connector(
    listing: RemoteListing | Exception, *, withdrawn: frozenset[str] = frozenset()
) -> MagicMock:
    async def download(remote_file: RemoteFile, dest_dir: Path, **_: Any) -> Path:
        if remote_file.source_path in withdrawn:
            raise WithdrawnFile(f"{remote_file.name} asks not to be indexed.")
        dest = dest_dir / remote_file.name
        dest.write_bytes(b"the page")
        return dest

    listed = (
        AsyncMock(side_effect=listing)
        if isinstance(listing, Exception)
        else AsyncMock(return_value=listing)
    )
    return MagicMock(
        list_files=listed,
        download_file=AsyncMock(side_effect=download),
        # The base's answers: no version to stop early on, nothing to release.
        remote_version=AsyncMock(return_value=None),
        aclose=AsyncMock(),
    )


@asynccontextmanager
async def _syncing(
    connector: MagicMock,
    *,
    unlisted: list[MagicMock],
    vectors_removed: bool = True,
    log: MagicMock | None = None,
) -> Any:
    source = MagicMock(
        id=SOURCE_ID,
        connector_type="web",
        config={"root_url": "https://docs.example.com/"},
        collection_name="docs",
        sync_mode="new_only",
        organization_id=uuid.uuid4(),
        secret_id=None,
        organizational_unit=None,
    )
    sources = MagicMock(
        get_source=AsyncMock(return_value=source),
        update_after_sync=AsyncMock(),
        trigger_sync=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
    )
    documents = MagicMock(
        create_document=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        complete_ingestion=AsyncMock(),
        fail_ingestion=AsyncMock(),
        unlisted_by_source=AsyncMock(return_value=unlisted),
        stale_for_source=AsyncMock(return_value=[]),
        forget_document=AsyncMock(),
    )
    syncs = MagicMock(complete_sync=AsyncMock(return_value=log))
    notifications = MagicMock(sync_completed=AsyncMock(), sync_failed=AsyncMock())
    remove = AsyncMock(return_value=vectors_removed)
    ingest = AsyncMock(
        return_value=MagicMock(
            status=IngestionStatus.DONE,
            document_id="vec-new",
            chunk_count=1,
            replaced_document_id=None,
            error_message=None,
        )
    )
    store = MagicMock(get_documents=AsyncMock(return_value=[]))
    store.find_existing_document = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _db() -> Any:
        yield MagicMock()

    with (
        patch.object(rag_tasks, "VectorStore", return_value=store),
        patch.object(rag_tasks, "EmbeddingService", new=MagicMock()),
        patch.object(rag_tasks, "get_worker_db_context", new=_db),
        patch.object(rag_tasks, "_record_embedding_spend", new=AsyncMock()),
        patch.object(rag_tasks, "assert_organization_within_budget", new=AsyncMock()),
        patch.object(rag_tasks, "SyncSourceService", return_value=sources),
        patch.object(rag_tasks, "_knowledge_base_for", new=AsyncMock(return_value=None)),
        patch.object(rag_tasks, "IngestionConfigService") as config_service,
        patch.object(rag_tasks, "NotificationService", return_value=notifications),
        patch.object(rag_tasks.IngestionService, "ingest_file", new=ingest),
        patch.object(rag_tasks.IngestionService, "remove_document", new=remove),
        patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"web": lambda: connector}),
        patch("app.services.rag_sync.RAGSyncService", return_value=syncs),
        patch("app.services.rag_document.RAGDocumentService", return_value=documents),
    ):
        config_service.return_value.build_processor = AsyncMock(return_value=MagicMock())
        config_service.return_value.resolved_image_model = AsyncMock(return_value=None)
        answer = await rag_tasks._run_source_sync(str(SOURCE_ID), sync_log_id=str(uuid.uuid4()))
        yield {
            "answer": answer,
            "notifications": notifications,
            "documents": documents,
            "remove": remove,
            "completed": syncs.complete_sync.call_args.kwargs,
            "source_error": sources.update_after_sync.call_args.kwargs["error"],
        }


class TestAgainstACompleteListing:
    async def test_a_document_the_source_no_longer_lists_is_removed(self) -> None:
        gone = _row("web://docs.example.com/gone")

        async with _syncing(_connector(RemoteListing(files=[KEPT])), unlisted=[gone]) as run:
            pass

        run["remove"].assert_awaited_once_with("docs", "vec-gone")
        run["documents"].forget_document.assert_awaited_once_with(str(gone.id))
        assert run["completed"]["removed"] == 1
        assert run["completed"]["status"] == "done"
        assert run["completed"]["error_message"] is None

    async def test_the_question_names_this_source_and_everything_it_listed(self) -> None:
        async with _syncing(_connector(RemoteListing(files=[KEPT])), unlisted=[]) as run:
            pass

        run["documents"].unlisted_by_source.assert_awaited_once_with(
            sync_source_id=SOURCE_ID, collection_name="docs", listed={KEPT.source_path}
        )
        assert run["completed"]["removed"] == 0

    async def test_rows_this_sync_opens_are_stamped_with_the_source(self) -> None:
        async with _syncing(_connector(RemoteListing(files=[KEPT])), unlisted=[]) as run:
            pass

        assert run["documents"].create_document.call_args.kwargs["sync_source_id"] == SOURCE_ID

    async def test_a_row_with_no_vectors_is_removed_without_asking_the_store(self) -> None:
        failed_before = _row("web://docs.example.com/broken", vector_document_id=None)

        async with _syncing(
            _connector(RemoteListing(files=[KEPT])), unlisted=[failed_before]
        ) as run:
            pass

        run["remove"].assert_not_awaited()
        assert run["completed"]["removed"] == 1

    async def test_a_failed_vector_delete_keeps_the_row_for_the_next_run(self) -> None:
        gone = _row("web://docs.example.com/gone")

        async with _syncing(
            _connector(RemoteListing(files=[KEPT])), unlisted=[gone], vectors_removed=False
        ) as run:
            pass

        run["documents"].forget_document.assert_not_awaited()
        assert run["completed"]["removed"] == 0
        # A failure of the run, not a detail: it must not report success, clear
        # the source's error and notify completion while the page is searchable.
        assert (run["completed"]["status"], run["completed"]["failed"]) == ("error", 1)
        assert run["completed"]["error_message"] == (
            "1 files failed. 1 documents the source no longer lists could not be removed and "
            "will be tried again by the next sync."
        )
        assert run["source_error"] == run["completed"]["error_message"]

    async def test_a_listed_page_the_fetch_finds_withdrawn_is_removed_not_failed(self) -> None:
        """A sitemap still naming a page that now says `noindex` must not keep
        it searchable: the fetch is the first the sync hears of it."""
        was_indexed = _row(HIDDEN.source_path)

        async with _syncing(
            _connector(
                RemoteListing(files=[KEPT, HIDDEN]), withdrawn=frozenset({HIDDEN.source_path})
            ),
            unlisted=[was_indexed],
        ) as run:
            pass

        run["documents"].unlisted_by_source.assert_awaited_once_with(
            sync_source_id=SOURCE_ID, collection_name="docs", listed={KEPT.source_path}
        )
        completed = run["completed"]
        assert (completed["status"], completed["failed"], completed["removed"]) == ("done", 0, 1)
        # Not one the source holds, so not one of the total either.
        assert (completed["total_files"], completed["ingested"]) == (1, 1)

    async def test_the_completion_notice_counts_what_was_removed(self) -> None:
        log = MagicMock(id=uuid.uuid4(), triggered_by_user_id=None)

        async with _syncing(
            _connector(RemoteListing(files=[KEPT])),
            unlisted=[_row("web://docs.example.com/gone")],
            log=log,
        ) as run:
            pass

        assert run["notifications"].sync_completed.await_args.kwargs["removed"] == 1
        assert run["answer"]["removed"] == 1


class TestAgainstAPartialListing:
    async def test_nothing_is_removed_and_the_log_says_why(self) -> None:
        listing = RemoteListing(files=[KEPT], complete=False)

        async with _syncing(
            _connector(listing), unlisted=[_row("web://docs.example.com/x")]
        ) as run:
            pass

        run["documents"].unlisted_by_source.assert_not_awaited()
        run["remove"].assert_not_awaited()
        assert run["completed"]["removed"] == 0
        # A ceiling is not a failure: the run is done, and says what it skipped.
        assert run["completed"]["status"] == "done"
        assert run["completed"]["error_message"].startswith(
            "The source could not be listed completely, so documents it may no longer hold were kept."
        )
        assert run["source_error"] is None

    async def test_pages_the_listing_could_not_read_count_as_failed_and_are_named(self) -> None:
        problems = [f"docs.example.com/p{n} answered HTTP 503." for n in range(4)]
        listing = RemoteListing(files=[KEPT], complete=False, problems=problems)

        async with _syncing(_connector(listing), unlisted=[]) as run:
            pass

        completed = run["completed"]
        assert (completed["status"], completed["failed"]) == ("error", 4)
        # Each problem is a page, so the total counts it: one read, four not.
        assert completed["total_files"] == 5
        assert completed["error_message"] == (
            "4 files failed. The source could not be listed completely, so documents it may no "
            "longer hold were kept. They are removed by the next complete sync. "
            "docs.example.com/p0 answered HTTP 503. docs.example.com/p1 answered HTTP 503. "
            "And 2 more."
        )
        assert run["source_error"] == completed["error_message"]


class TestWhenTheListingItselfFails:
    async def test_our_own_refusal_is_recorded_whole(self) -> None:
        refusal = BadRequestError(
            message="The site's robots.txt could not be read, so it was not crawled."
        )

        async with _syncing(_connector(refusal), unlisted=[_row("web://x")]) as run:
            pass

        run["documents"].unlisted_by_source.assert_not_awaited()
        assert run["completed"]["error_message"] == (
            "1 files failed. The site's robots.txt could not be read, so it was not crawled."
        )

    async def test_a_foreign_failure_is_reduced_to_its_type(self) -> None:
        async with _syncing(
            _connector(RuntimeError("https://internal/?key=secret")), unlisted=[]
        ) as run:
            pass

        assert "secret" not in run["completed"]["error_message"]
        assert "(RuntimeError)" in run["completed"]["error_message"]


class TestOneRunOfASourceAtATime:
    """An older run's listing does not name what a newer, overlapping run just
    ingested, and would remove it - so a run that cannot take its source's lock
    does nothing but say so."""

    @asynccontextmanager
    async def _held_elsewhere(self, sync_log_id: str | None) -> Any:
        @asynccontextmanager
        async def _lock(_source_id: str) -> Any:
            yield False

        connector = _connector(RemoteListing(files=[KEPT]))
        syncs = MagicMock(complete_sync=AsyncMock(return_value=None))
        with (
            patch.object(rag_tasks, "_exclusive_source_run", new=_lock),
            patch.object(rag_tasks, "get_worker_db_context", new=_no_db),
            patch.dict(rag_tasks.CONNECTOR_REGISTRY, {"web": lambda: connector}),
            patch("app.services.rag_sync.RAGSyncService", return_value=syncs),
        ):
            answer = await rag_tasks._run_source_sync(str(SOURCE_ID), sync_log_id=sync_log_id)
            yield answer, connector, syncs.complete_sync

    async def test_a_run_that_cannot_take_the_lock_reads_nothing_and_says_why(self) -> None:
        async with self._held_elsewhere("log-1") as (answer, connector, complete):
            pass

        connector.list_files.assert_not_awaited()
        assert answer["status"] == "skipped"
        assert complete.await_args.kwargs == {
            "status": "error",
            "error_message": rag_tasks.OVERLAPPING_RUN,
        }

    async def test_a_scheduler_dispatch_with_no_log_writes_none(self) -> None:
        async with self._held_elsewhere(None) as (answer, _connector, complete):
            pass

        assert answer["status"] == "skipped"
        complete.assert_not_awaited()


@asynccontextmanager
async def _no_db() -> Any:
    yield MagicMock()
