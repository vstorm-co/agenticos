"""The parse scratch copy of an upload goes when nothing will read it again (#2681).

Every upload and every retry writes `MEDIA_DIR/_rag_tmp/<document>-<attempt><ext>`
for its `ingest-document` job to parse, and until #2681 nothing removed it: the
copy outlived the ingest, the document, its knowledge base and the account that
uploaded it, so a deleted document's full content stayed on the API host's disk.

Removed when its job ends - done, refused, the document gone, or failed on its
last attempt - and kept while the queue may still retry it; removed when the
document is deleted; and swept hourly once its document is gone or settled, for
whatever a lost job or a deployment from before the fix left behind.
"""

import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.core import background
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.db.models.rag_document import DocumentStatus
from app.repositories import rag_document_repo
from app.services import rag_scratch
from app.services.rag.models import IngestionResult, IngestionStatus
from app.services.rag_document import RAGDocumentService
from app.worker import jobs
from app.worker.attempt import Attempt, running
from app.worker.handlers import production
from app.worker.schedules import SCHEDULES
from app.worker.tasks import rag_tasks, teardown_tasks

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def media(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """`MEDIA_DIR` in a temporary directory, with its scratch directory made."""
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    scratch = tmp_path / "_rag_tmp"
    scratch.mkdir()
    return scratch


def _copy(scratch: Path, name: str, *, age: timedelta = timedelta(hours=2)) -> Path:
    path = scratch / name
    path.write_bytes(b"the whole of somebody's document")
    stamp = (NOW - age).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def _job(path: Path, *, document_id: uuid.UUID | None = None) -> jobs.IngestDocument:
    return jobs.IngestDocument(
        rag_document_id=document_id or uuid.uuid4(),
        collection_name="handbooks",
        filepath=str(path),
        source_path="policy.pdf",
        replace=False,
        attempt=1,
    )


class TestWhereACopyLives:
    def test_each_dispatch_has_a_file_of_its_own(self, media: Path) -> None:
        """A retry's copy must not share a name with the copy the failed job's cleanup
        removes: that cleanup can run after the person already pressed Retry."""
        document = uuid.uuid4()

        first = rag_scratch.scratch_path(document, attempt=1, suffix=".pdf")
        second = rag_scratch.scratch_path(document, attempt=2, suffix=".pdf")

        assert first == media / f"{document}-1.pdf"
        assert second == media / f"{document}-2.pdf"


class TestRemovingOneCopy:
    def test_a_copy_is_removed(self, media: Path) -> None:
        path = _copy(media, f"{uuid.uuid4()}-1.pdf")

        assert rag_scratch.discard(path) is True
        assert not path.exists()

    def test_a_copy_already_gone_is_not_an_error(self, media: Path) -> None:
        assert rag_scratch.discard(media / f"{uuid.uuid4()}-1.pdf") is False

    @pytest.mark.security
    def test_a_path_outside_the_scratch_directory_is_never_removed(
        self, media: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The path comes off a job's payload: it is only ever removed where the
        upload wrote it."""
        stored = media.parent / "rag" / "handbooks" / "policy.pdf"
        stored.parent.mkdir(parents=True)
        stored.write_bytes(b"the permanent copy")

        with caplog.at_level(logging.WARNING, logger="app.services.rag_scratch"):
            assert rag_scratch.discard(stored) is False

        assert stored.exists()
        assert "not a parse scratch copy" in caplog.text

    def test_a_copy_that_cannot_be_removed_is_logged_not_raised(
        self, media: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _copy(media, f"{uuid.uuid4()}-1.pdf")
        monkeypatch.setattr(Path, "unlink", MagicMock(side_effect=PermissionError("read-only")))

        with caplog.at_level(logging.WARNING, logger="app.services.rag_scratch"):
            assert rag_scratch.discard(path) is False

        assert "read-only" in caplog.text

    async def test_every_name_a_documents_dispatches_had_is_removed(self, media: Path) -> None:
        """The upload's, each retry's, and the one name a deployment from before the
        fix gave it - and nobody else's."""
        document = uuid.uuid4()
        mine = [
            _copy(media, f"{document}.pdf"),
            _copy(media, f"{document}-1.pdf"),
            _copy(media, f"{document}-2.pdf"),
        ]
        neighbour = _copy(media, f"{uuid.uuid4()}-1.pdf")

        removed = await rag_scratch.discard_document(document, suffix=".pdf", attempts=2)

        assert removed == 3
        assert not any(path.exists() for path in mine)
        assert neighbour.exists()


class TestTheSweep:
    """What a lost job, or a deployment from before #2681, left in the directory."""

    @staticmethod
    def _processing(*ids: uuid.UUID) -> AsyncMock:
        async def among(_db: object, doc_ids: list[uuid.UUID]) -> set[uuid.UUID]:
            return {doc_id for doc_id in doc_ids if doc_id in ids}

        return AsyncMock(side_effect=among)

    async def test_only_a_copy_nothing_will_parse_again_is_removed(
        self, media: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        processing = uuid.uuid4()
        settled_or_gone = _copy(media, f"{uuid.uuid4()}-1.pdf")
        legacy = _copy(media, f"{uuid.uuid4()}.docx")
        queued = _copy(media, f"{processing}-1.pdf")
        # Written before its upload commits: no row can be seen for it yet.
        in_flight = _copy(media, f"{uuid.uuid4()}-1.pdf", age=timedelta(minutes=5))
        foreign = _copy(media, "notes.txt")
        (media / f"{uuid.uuid4()}-1.d").mkdir()
        monkeypatch.setattr(rag_document_repo, "processing_among", self._processing(processing))

        swept = await rag_scratch.sweep_stale(MagicMock(), now=NOW)

        assert swept == rag_scratch.ScratchSweep(removed=2, kept=1)
        assert not settled_or_gone.exists()
        assert not legacy.exists()
        assert queued.exists()
        assert in_flight.exists()
        assert foreign.exists()

    async def test_the_documents_are_looked_up_in_bounded_batches(
        self, media: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for _ in range(5):
            _copy(media, f"{uuid.uuid4()}-1.pdf")
        lookup = self._processing()
        monkeypatch.setattr(rag_document_repo, "processing_among", lookup)
        monkeypatch.setattr(rag_scratch, "_LOOKUP_BATCH", 2)

        swept = await rag_scratch.sweep_stale(MagicMock(), now=NOW)

        assert swept.removed == 5
        assert [len(call.args[1]) for call in lookup.await_args_list] == [2, 2, 1]

    async def test_a_copy_removed_while_the_sweep_ran_is_skipped(
        self, media: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gone = _copy(media, f"{uuid.uuid4()}-1.pdf")
        real_stat = Path.stat

        def stat(path: Path, **kwargs: object) -> os.stat_result:
            if path == gone:
                raise FileNotFoundError(path)
            return real_stat(path, **kwargs)

        monkeypatch.setattr(Path, "stat", stat)
        monkeypatch.setattr(rag_document_repo, "processing_among", self._processing())

        assert await rag_scratch.sweep_stale(MagicMock(), now=NOW) == rag_scratch.ScratchSweep(
            removed=0, kept=0
        )

    async def test_no_scratch_directory_is_nothing_to_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path / "absent"))
        lookup = AsyncMock()
        monkeypatch.setattr(rag_document_repo, "processing_among", lookup)

        swept = await rag_scratch.sweep_stale(MagicMock(), now=NOW)

        assert swept == rag_scratch.ScratchSweep(removed=0, kept=0)
        lookup.assert_not_awaited()

    async def test_which_documents_are_still_processing_is_one_query(self) -> None:
        found = uuid.uuid4()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [found]
        db = MagicMock(execute=AsyncMock(return_value=result))

        assert await rag_document_repo.processing_among(db, [found, uuid.uuid4()]) == {found}
        sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
        assert sql.startswith("SELECT rag_documents.id")
        assert "rag_documents.id IN" in sql
        assert "rag_documents.status =" in sql

    async def test_the_worker_sweeps_hourly_on_a_session_of_its_own(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = MagicMock()

        @asynccontextmanager
        async def worker_db() -> AsyncIterator[MagicMock]:
            yield session

        sweep = AsyncMock(return_value=rag_scratch.ScratchSweep(removed=3, kept=1))
        monkeypatch.setattr("app.db.session.get_worker_db_context", worker_db)
        monkeypatch.setattr(rag_scratch, "sweep_stale", sweep)

        assert await teardown_tasks.sweep_rag_scratch() == {"removed": 3, "kept": 1}
        assert sweep.await_args.args == (session,)
        [schedule] = [s for s in SCHEDULES if s.task is jobs.SWEEP_RAG_SCRATCH]
        assert schedule.every == timedelta(hours=1)
        assert jobs.SWEEP_RAG_SCRATCH.kind in production()


class TestTheIngestJob:
    """The job is the copy's owner: it removes it once no attempt of it is coming."""

    @pytest.mark.parametrize(
        "outcome",
        [
            {"status": "done", "document_id": "vec-1", "filename": "policy.pdf"},
            {"status": "refused", "filename": "policy.pdf", "message": "gone"},
            {"status": "deleted", "filename": "policy.pdf"},
        ],
        ids=["done", "refused", "document-gone"],
    )
    async def test_a_job_that_ends_removes_its_copy(
        self, media: Path, monkeypatch: pytest.MonkeyPatch, outcome: dict[str, str]
    ) -> None:
        path = _copy(media, f"{uuid.uuid4()}-1.pdf")
        monkeypatch.setattr(rag_tasks, "_run_ingestion", AsyncMock(return_value=outcome))

        with running(Attempt(1, 2)):
            assert await rag_tasks.ingest_document(_job(path)) == outcome

        assert not path.exists()

    async def test_a_failure_on_the_last_attempt_removes_it(
        self, media: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _copy(media, f"{uuid.uuid4()}-1.pdf")
        monkeypatch.setattr(rag_tasks, "_run_ingestion", AsyncMock(side_effect=RuntimeError("x")))
        monkeypatch.setattr(rag_tasks, "_fail_document", AsyncMock())

        with running(Attempt(2, 2)), pytest.raises(RuntimeError):
            await rag_tasks.ingest_document(_job(path))

        assert not path.exists()

    async def test_a_failure_the_queue_retries_keeps_it(
        self, media: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The retry parses the same file: removing it would fail the retry for a
        reason the first attempt invented."""
        path = _copy(media, f"{uuid.uuid4()}-1.pdf")
        monkeypatch.setattr(rag_tasks, "_run_ingestion", AsyncMock(side_effect=RuntimeError("x")))
        monkeypatch.setattr(rag_tasks, "_fail_document", AsyncMock())

        with running(Attempt(1, 2)), pytest.raises(RuntimeError):
            await rag_tasks.ingest_document(_job(path))

        assert path.exists()

    async def test_a_job_given_back_keeps_it(
        self, media: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancelled - a shutdown or a lost lease - is not ended: the job runs again."""
        import asyncio

        path = _copy(media, f"{uuid.uuid4()}-1.pdf")
        monkeypatch.setattr(
            rag_tasks, "_run_ingestion", AsyncMock(side_effect=asyncio.CancelledError())
        )

        with running(Attempt(2, 2)), pytest.raises(asyncio.CancelledError):
            await rag_tasks.ingest_document(_job(path))

        assert path.exists()

    async def test_a_copy_that_cannot_be_removed_does_not_change_the_outcome(
        self, media: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outcome = {"status": "done", "document_id": "vec-1", "filename": "policy.pdf"}
        monkeypatch.setattr(rag_tasks, "_run_ingestion", AsyncMock(return_value=outcome))
        monkeypatch.setattr(rag_scratch, "discard", MagicMock(side_effect=RuntimeError("disk")))

        assert await rag_tasks.ingest_document(_job(media / "x-1.pdf")) == outcome

    async def test_a_job_the_queue_wrote_off_removes_it(
        self, media: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A child killed on its last attempt never reaches its own cleanup; the
        settler the queue runs once no attempt is coming does."""
        path = _copy(media, f"{uuid.uuid4()}-1.pdf")
        monkeypatch.setattr(rag_tasks, "_fail_document", AsyncMock())

        await rag_tasks.settle_lost_ingest(_job(path), "killed")

        assert not path.exists()


@asynccontextmanager
async def _worker_db() -> AsyncIterator[MagicMock]:
    yield MagicMock()


class TestADocumentDeletedBeforeItIndexed:
    """A delete or a teardown removes the row while its job is queued or parsing."""

    async def test_a_job_whose_document_is_gone_ends_without_a_retry(
        self, media: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What a knowledge-base, collection, account or organization teardown leaves
        a processing document's job: no row. The job ends cleanly and takes the copy
        with it, instead of raising into a retry that cannot succeed."""
        path = _copy(media, f"{uuid.uuid4()}-1.pdf")
        documents = MagicMock()
        documents.return_value.get_document = AsyncMock(
            side_effect=NotFoundError(message="Document not found")
        )
        monkeypatch.setattr(rag_tasks, "get_worker_db_context", _worker_db)
        monkeypatch.setattr("app.services.rag_document.RAGDocumentService", documents)

        with running(Attempt(1, 2)):
            outcome = await rag_tasks.ingest_document(_job(path))

        assert outcome == {"status": "deleted", "filename": "policy.pdf"}
        assert not path.exists()

    async def test_a_parse_that_lost_its_copy_to_a_delete_is_a_refusal(
        self, media: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The delete removes the copy after its commit; a parser that had not opened
        it yet fails to read it. The document is gone, so that is a refusal - not an
        error to retry and trace."""
        documents = MagicMock()
        documents.return_value.get_document = AsyncMock(
            return_value=MagicMock(
                organization_id=None,
                ingestion_config={},
                status=DocumentStatus.PROCESSING,
                knowledge_base_id=None,
            )
        )
        pipeline = MagicMock()
        pipeline.ingest_file = AsyncMock(
            return_value=IngestionResult(
                status=IngestionStatus.ERROR, error_message="The file could not be read"
            )
        )

        @asynccontextmanager
        async def _pipeline(**_kwargs: object) -> AsyncIterator[MagicMock]:
            yield pipeline

        fail = AsyncMock()
        monkeypatch.setattr(rag_tasks, "get_worker_db_context", _worker_db)
        monkeypatch.setattr("app.services.rag_document.RAGDocumentService", documents)
        monkeypatch.setattr(
            "app.services.ingestion_config.IngestionConfigService.build_processor", AsyncMock()
        )
        monkeypatch.setattr(rag_tasks, "_ingestion_service", _pipeline)
        monkeypatch.setattr(rag_tasks, "_record_embedding_spend", AsyncMock())
        monkeypatch.setattr(rag_tasks, "_still_ingestable", AsyncMock(return_value=False))
        monkeypatch.setattr(rag_tasks, "_fail_document", fail)
        document = str(uuid.uuid4())

        with running(Attempt(1, 2)):
            outcome = await rag_tasks._run_ingestion(
                document, "handbooks", str(media / "gone-1.pdf"), "policy.pdf", False, 1
            )

        assert outcome["status"] == "refused"
        assert fail.await_args.kwargs["final"] is True


@pytest.fixture
def _no_leftover_tasks():
    background._running.clear()
    yield
    background._running.clear()


@pytest.mark.usefixtures("_no_leftover_tasks")
class TestDeletingADocument:
    async def test_its_copy_goes_after_the_delete_commits(
        self, media: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deleting a document that is still processing removes the content it was
        uploaded with from the scratch directory too - after the commit, so a
        rolled-back delete keeps the copy its job still needs."""
        row = SimpleNamespace(
            id=uuid.uuid4(),
            collection_name="docs",
            vector_document_id=None,
            storage_path="rag/docs/policy.pdf",
            knowledge_base_id=None,
            filename="Policy.PDF",
            ingestion_attempt=2,
        )
        copies = [_copy(media, f"{row.id}-1.pdf"), _copy(media, f"{row.id}-2.pdf")]
        monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=row))
        monkeypatch.setattr(
            rag_document_repo,
            "delete_with_vectors",
            AsyncMock(
                return_value=rag_document_repo.DeletedDocuments(
                    storage_paths=[], vector_document_ids=[]
                )
            ),
        )
        db = MagicMock()
        db.info = {}

        await RAGDocumentService(db).delete_document(str(row.id), MagicMock())
        assert all(path.exists() for path in copies)

        background.start_deferred(db)
        await background.drain(timeout=5.0)
        assert not any(path.exists() for path in copies)
