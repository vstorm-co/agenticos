"""PII redaction has to run on what the application actually logs.

The filter was attached to the root *logger*, where it scrubbed nothing: every
line here comes from `logging.getLogger(__name__)`, and a module logger's record
reaches the root's *handlers*, never its filters (#440). And the worker, which
runs the ingestion and the syncs, never set logging up at all. So the tests that
matter are: a record logged through a module logger comes out redacted, an
unconfigured process is still covered, and the two entrypoints that were missing
the call now make it.
"""

from __future__ import annotations

import io
import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.core.logging import PiiRedactionFilter, setup_logging

# Built from fragments on purpose: the test proves the filter strips a credential
# at runtime, so a static secret-scanner must not read a literal one flowing into
# a log sink here (it is a fixture, not a leak).
_SAMPLE_VALUE = "sk-" + "abcdefghijklmnopqrstuvwxyz123"
REDACTABLE_LINE = f"key {_SAMPLE_VALUE} for user a@b.com"


@pytest.fixture
def root_stream():
    """A stream handler on the root logger, snapshotted and restored.

    Restored fully because the redaction filter is attached to whatever handlers
    exist, and a filter left on `logging.lastResort` would leak into other tests.
    """
    root = logging.getLogger()
    # setup_logging attaches a filter to every handler that exists when it runs,
    # so snapshot them all - not just the one this test adds - and restore, or a
    # filter left on a persistent handler redacts another test's assertions.
    touched = [*root.handlers]
    if logging.lastResort is not None:
        touched.append(logging.lastResort)
    saved = {handler: list(handler.filters) for handler in touched}

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    root.addHandler(handler)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        for touched_handler, filters in saved.items():
            touched_handler.filters = filters


def test_a_module_logger_record_is_redacted_at_the_handler(root_stream):
    """The defect in one assertion: the line is emitted by a module logger, and
    the filter used to sit where a module logger's record never reaches."""
    setup_logging()

    logging.getLogger("app.services.rag.ingestion").error(REDACTABLE_LINE)

    emitted = root_stream.getvalue()
    assert "[API_KEY_REDACTED]" in emitted
    assert "[EMAIL_REDACTED]" in emitted
    assert _SAMPLE_VALUE not in emitted
    assert "a@b.com" not in emitted


def test_a_credential_in_an_exception_traceback_is_redacted(root_stream):
    """The leak this filter is for: a provider error carries the failing request,
    key and all, and the formatter appends it from `exc_info` after the filter has
    run on the message - so scrubbing only `msg` lets the traceback through."""
    setup_logging()

    def _fail_with_credential() -> None:
        raise RuntimeError(f"POST https://api.example.com refused; key {_SAMPLE_VALUE}")

    try:
        _fail_with_credential()
    except RuntimeError:
        logging.getLogger("app.services.rag.ingestion").exception("Ingestion failed")

    emitted = root_stream.getvalue()
    assert "[API_KEY_REDACTED]" in emitted
    assert _SAMPLE_VALUE not in emitted


def test_setup_logging_is_idempotent(root_stream):
    """Called from three entrypoints and safe to call again, so a handler does not
    collect one filter per call."""
    setup_logging()
    setup_logging()

    handler = logging.getLogger().handlers[-1]
    assert sum(isinstance(f, PiiRedactionFilter) for f in handler.filters) == 1


def test_an_unconfigured_process_redacts_through_last_resort(root_stream):
    """A process with no root handler emits WARNING+ through `logging.lastResort`,
    and a credential in a `logger.exception` is exactly that. Covered without
    adding a handler or changing a level."""
    setup_logging()

    assert logging.lastResort is not None
    assert any(isinstance(f, PiiRedactionFilter) for f in logging.lastResort.filters)


def test_the_worker_sets_logging_up():
    """The worker ran the ingestion and syncs in a process that never called
    setup_logging, so even redactable lines were not redacted (#440)."""
    from app.worker import prefect_app

    with (
        patch.object(prefect_app, "setup_logging") as configure,
        patch.object(
            prefect_app.ingest_document_flow,
            "ato_deployment",
            new=AsyncMock(side_effect=RuntimeError("stop after setup")),
        ),
        pytest.raises(RuntimeError),
    ):
        import anyio

        anyio.run(prefect_app.main)

    configure.assert_called_once()


def test_the_cli_sets_logging_up():
    from cli import commands

    with (
        patch.object(commands, "setup_logging") as configure,
        patch.object(commands, "cli") as cli,
    ):
        commands.main()

    configure.assert_called_once()
    cli.assert_called_once()
