"""A failed ingest says what failed, not where (#423).

`rag_documents.error_message` and `sync_logs.error_message` are stored columns
rendered to every member who can see the collection, and they held `str(exc)`
from whatever raised - an embedding client, `httpx`, `boto3`. A provider SDK
puts the failing request in its message, and a URL carries a key in its query
string, so the leak #342 fixed in an HTTP body was still being *written down*
on the ingestion path.

Every test here asserts both halves, because moving the diagnosis is the fix
and deleting it would be a different bug: the stored string carries none of the
upstream's text, and the log line carries all of it. Most of these call sites
are template-inherited worker code that `make coverage-all` reports and no gate
enforces, which is the reason to pin the behaviour by name rather than to trust
a percentage.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope
from app.core.exceptions import ConfigurationError
from app.db.models.rag_document import DocumentStatus
from app.services.rag.failures import IngestionStage, failure_summary
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import IngestionStatus
from app.worker.tasks.rag_tasks import _fail_document, _run_ingestion

pytestmark = pytest.mark.anyio

# What an embedding client actually says when a key is wrong: the endpoint it
# called, and the key it called it with.
_VENDOR_TEXT = (
    "Error code: 401 - authentication failed for "
    "https://embeddings.internal.acme.example/v1/embeddings?api-key=sk-live-9f3ca2"
)


class AuthenticationError(Exception):
    """Stands in for a provider SDK's exception - the name is the point.

    A vendor class name is a symbol rather than a value, which is why the
    summary is allowed to keep it: it says the credential was refused without
    saying which host refused it.
    """


def _vendor_failure() -> AuthenticationError:
    return AuthenticationError(_VENDOR_TEXT)


def _assert_leaks_nothing(stored: str) -> None:
    assert "sk-live-9f3ca2" not in stored
    assert "embeddings.internal.acme.example" not in stored
    assert "Error code: 401" not in stored


class TestWhatMayBeStored:
    def test_a_vendor_exception_reaches_the_column_as_a_stage_and_a_type(self):
        summary = failure_summary(_vendor_failure(), stage=IngestionStage.INDEX)

        _assert_leaks_nothing(summary)
        assert summary == (
            "The document could not be indexed (AuthenticationError) - check the "
            "collection's embedding credential, then retry the upload. "
            "The worker log has the full error."
        )

    def test_the_stage_the_call_site_names_is_the_stage_the_reader_is_told(self):
        """Which stage gave up is the one thing the reader cannot work out."""
        assert failure_summary(_vendor_failure(), stage=IngestionStage.PARSE).startswith(
            "The file could not be read (AuthenticationError)"
        )
        assert failure_summary(_vendor_failure(), stage=IngestionStage.SYNC).startswith(
            "The sync did not finish (AuthenticationError)"
        )
        assert failure_summary(_vendor_failure(), stage=IngestionStage.RECORD).startswith(
            "The document was indexed but its record was not updated (AuthenticationError)"
        )

    def test_our_own_refusal_is_kept_whole(self):
        """An `AppException`'s message is written in this repository.

        Replacing "no embedding credential is configured for this collection"
        with a generic sentence would answer the question the reader is asking -
        credential, file, or upstream - with a shrug.
        """
        ours = ConfigurationError(
            message="No embedding credential is configured for the collection's key",
            details={"setting": "OPENROUTER_API_KEY"},
        )

        assert failure_summary(ours, stage=IngestionStage.INDEX) == (
            "No embedding credential is configured for the collection's key"
        )

    def test_a_budget_refusal_keeps_its_numbers(self):
        """`BudgetExceeded` is ours too, and the numbers are the organization's.

        The worker refuses a queued document at the cap and puts that refusal on
        the row deliberately - reducing it to "(BudgetExceeded)" would undo it.
        """
        refusal = BudgetExceeded(
            limit_usd=Decimal("40.00"),
            spent_usd=Decimal("40.15"),
            scope=BudgetScope.ORGANIZATION,
        )

        assert failure_summary(refusal, stage=IngestionStage.SYNC) == (
            "Organization monthly budget exhausted: $40.1500 spent of $40.00 limit"
        )

    def test_a_task_group_is_unwrapped_before_it_is_named(self):
        """The connector clients run on anyio task groups.

        Their failures arrive as "unhandled errors in a TaskGroup", which names
        nothing at all - so the type reported is the leaf's, not the group's.
        """
        nested = ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [ExceptionGroup("inner", [_vendor_failure()])],
        )

        summary = failure_summary(nested, stage=IngestionStage.SYNC)

        _assert_leaks_nothing(summary)
        assert "(AuthenticationError)" in summary
        assert "TaskGroup" not in summary

    def test_every_stage_says_something_and_advises_something(self):
        for stage in IngestionStage:
            assert stage.summary and stage.advice
            assert not stage.summary.endswith(".")


class TestTheIngestionServiceMovesItToTheLog:
    """`IngestionService.ingest_file` is where the text used to be born."""

    @staticmethod
    def _service(*, parse: AsyncMock, insert: AsyncMock) -> IngestionService:
        processor = MagicMock(process_file=parse)
        store = MagicMock(insert_document=insert)
        return IngestionService(processor=processor, vector_store=store)

    @staticmethod
    def _document() -> MagicMock:
        return MagicMock(
            id="doc-1",
            chunked_pages=[],
            metadata=MagicMock(source_path="", content_hash=None),
        )

    async def test_an_indexing_failure_stores_a_summary_and_logs_the_upstream(
        self, caplog: pytest.LogCaptureFixture
    ):
        service = self._service(
            parse=AsyncMock(return_value=self._document()),
            insert=AsyncMock(side_effect=_vendor_failure()),
        )

        with caplog.at_level(logging.ERROR, logger="app.services.rag.ingestion"):
            result = await service.ingest_file(
                filepath=Path("/srv/uploads/handbook.pdf"), collection_name="kb_ops", replace=False
            )

        assert result.status is IngestionStatus.ERROR
        assert result.error_message is not None
        _assert_leaks_nothing(result.error_message)
        assert "(AuthenticationError)" in result.error_message
        # Moved, not deleted: the whole of it, with a traceback, one line away.
        assert _VENDOR_TEXT in caplog.text
        assert "Indexing failed for handbook.pdf" in caplog.text

    async def test_a_parse_failure_says_parse_rather_than_index(
        self, caplog: pytest.LogCaptureFixture
    ):
        """The parser's own message names the temporary file it was handed.

        `LiteParseParser` raises `RuntimeError(f"LiteParse: file not found:
        {filepath}")`, so even our own text here is a server path - the reason
        the rule is "ours means an `AppException`", not "ours means we wrote it".
        """
        service = self._service(
            parse=AsyncMock(
                side_effect=RuntimeError("LiteParse: file not found: /srv/tmp/x7/handbook.pdf")
            ),
            insert=AsyncMock(),
        )

        with caplog.at_level(logging.ERROR, logger="app.services.rag.ingestion"):
            result = await service.ingest_file(
                filepath=Path("/srv/tmp/x7/handbook.pdf"), collection_name="kb_ops"
            )

        assert result.error_message is not None
        assert "/srv/tmp/x7" not in result.error_message
        assert result.error_message.startswith("The file could not be read (RuntimeError)")
        assert "/srv/tmp/x7/handbook.pdf" in caplog.text


class TestWhatTheWorkerWritesToTheRow:
    """The two handlers that put a failure on `rag_documents` for a reader."""

    @staticmethod
    @asynccontextmanager
    async def _db():
        yield MagicMock()

    async def test_the_flow_records_a_summary_when_the_pipeline_raises(self):
        """`_run_ingestion` is where an upload's failure becomes a row.

        `ingest_file` returns its failures rather than raising them, so this
        handler catches what escapes the metering window - and used to write
        `str(e)` to the column the documents page renders.
        """
        documents = MagicMock()
        documents.return_value.get_document = AsyncMock(
            return_value=MagicMock(
                organization_id=None, ingestion_config={}, status=DocumentStatus.PROCESSING
            )
        )
        documents.return_value.fail_ingestion = AsyncMock()
        pipeline = MagicMock()
        pipeline.ingest_file = AsyncMock(side_effect=_vendor_failure())
        # Disposed in the flow's `finally`, whether the ingest raised or not (#948).
        pipeline.store = MagicMock(aclose=AsyncMock())

        with (
            patch("app.worker.tasks.rag_tasks.get_worker_db_context", self._db),
            patch("app.services.rag_document.RAGDocumentService", documents),
            patch(
                "app.worker.tasks.rag_tasks._ingestion_service_for",
                new=AsyncMock(return_value=pipeline),
            ),
            patch("app.worker.tasks.rag_tasks._record_embedding_spend", new=AsyncMock()),
            pytest.raises(AuthenticationError),
        ):
            await _run_ingestion(str(uuid.uuid4()), "kb_ops", "/srv/uploads/f.pdf", "f.pdf", False)

        stored = documents.return_value.fail_ingestion.await_args.kwargs["error_message"]
        _assert_leaks_nothing(stored)
        assert stored.startswith("The document could not be ingested (AuthenticationError)")

    async def test_the_first_handler_to_report_a_failure_is_the_one_that_is_kept(self):
        """Three handlers report one collapse, and they run innermost first.

        The innermost knows the stage - "could not be indexed, check the
        collection's embedding credential"; the flow's backstop only knows the
        ingest failed. While every level wrote the same `str(exc)` the order did
        not matter; now the outermost write would replace the useful sentence
        with the vague one.
        """
        documents = MagicMock()
        documents.return_value.get_document = AsyncMock(
            return_value=MagicMock(status=DocumentStatus.ERROR)
        )
        documents.return_value.fail_ingestion = AsyncMock()

        with (
            patch("app.worker.tasks.rag_tasks.get_worker_db_context", self._db),
            patch("app.services.rag_document.RAGDocumentService", documents),
        ):
            await _fail_document(str(uuid.uuid4()), error_message="the vague one")

        documents.return_value.fail_ingestion.assert_not_awaited()

    async def test_a_row_that_has_not_failed_yet_takes_the_failure(self):
        """The other half of the guard above: the first handler does write."""
        documents = MagicMock()
        documents.return_value.get_document = AsyncMock(
            return_value=MagicMock(status=DocumentStatus.PROCESSING)
        )
        documents.return_value.fail_ingestion = AsyncMock()

        with (
            patch("app.worker.tasks.rag_tasks.get_worker_db_context", self._db),
            patch("app.services.rag_document.RAGDocumentService", documents),
        ):
            await _fail_document(str(uuid.uuid4()), error_message="the specific one")

        assert (
            documents.return_value.fail_ingestion.await_args.kwargs["error_message"]
            == "the specific one"
        )
