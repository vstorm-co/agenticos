"""PII redaction has to run on what the application actually logs.

The filter was attached to the root *logger*, where it scrubbed nothing: every
line here comes from `logging.getLogger(__name__)`, and a module logger's record
reaches the root's *handlers*, never its filters (#440). And the worker, which
runs the ingestion and the syncs, never set logging up at all. So the tests that
matter are: a record logged through a module logger comes out redacted, an
unconfigured process is still covered, and the two entrypoints that were missing
the call now make it.
"""

import copy
import io
import logging
import logging.config
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from uvicorn.config import LOGGING_CONFIG

from app.core.logging import PiiRedactionFilter, one_line, setup_logging

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


@pytest.mark.security
def test_a_submitted_value_cannot_write_a_log_entry_of_its_own(root_stream):
    """One entry is one line, so a value carrying a newline writes a second one -
    with a timestamp, a level and a message of the sender's choosing - an address
    somebody typed into a sign-in form, say (`py/log-injection`)."""
    setup_logging()

    logging.getLogger("app.services.rate_limit").warning(
        "Rate limiting not configured - %s reached unmetered by %s",
        "auth",
        "id:nobody\n2026-01-01 12:00:00 CRITICAL app.audit: admin promoted somebody",
    )

    emitted = root_stream.getvalue()
    assert "CRITICAL app.audit" in emitted, "the attempt is still recorded, not swallowed"
    assert emitted.count("\n") == 1, "and it is one entry, on one line"
    assert "\\n2026-01-01" in emitted


@pytest.mark.security
def test_a_value_passed_through_extra_is_escaped_too(root_stream):
    """The default formatter does not render `extra`, so this forges nothing
    today - but a deployment that plugs in a JSON or key-value formatter, which is
    the ordinary production choice, must not acquire the hole by doing so."""
    setup_logging()
    record = logging.LogRecord("app.x", logging.WARNING, "p", 1, "embed_origin_refused", None, None)
    record.origin = "https://evil.example\r\n2026-01-01 FORGED"

    PiiRedactionFilter().filter(record)

    assert record.origin == "https://evil.example\\r\\n2026-01-01 FORGED"


def test_a_tab_survives_because_it_breaks_no_line(root_stream):
    """Escaping is about what ends a line, not about flattening a message
    somebody wrote deliberately."""
    assert PiiRedactionFilter()._redact("a\tb") == "a\tb"


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


_LINK_TOKEN = "1761200000." + "ab" * 32
_ACCESS_PATH = f"/api/v1/embed/pk/generated/0123456789ab_image.png?token={_LINK_TOKEN}"


@pytest.fixture
def uvicorn_access() -> Iterator[io.StringIO]:
    """uvicorn's loggers as `uvicorn app.main:app` configures them, then put back.

    Its `LOGGING_CONFIG` gives `uvicorn.access` a handler of its own and turns
    propagation off, so nothing it writes reaches the root's handlers.
    """
    loggers = [logging.getLogger(name) for name in ("uvicorn", "uvicorn.access", "uvicorn.error")]
    saved = [
        (logger, list(logger.handlers), list(logger.filters), logger.propagate, logger.level)
        for logger in loggers
    ]
    logging.config.dictConfig(copy.deepcopy(LOGGING_CONFIG))
    stream = io.StringIO()
    for handler in logging.getLogger("uvicorn.access").handlers:
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(stream)
    try:
        yield stream
    finally:
        for logger, handlers, filters, propagate, level in saved:
            logger.handlers = handlers
            logger.filters = filters
            logger.propagate = propagate
            logger.setLevel(level)


def _access_line() -> None:
    """One request line, in the shape uvicorn's HTTP protocol logs it."""
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "10.0.0.5:1234", "GET", _ACCESS_PATH, "1.1", 200
    )


def test_a_signed_link_in_the_access_log_is_redacted(uvicorn_access):
    """uvicorn configures its loggers before the app is imported, so the access
    log's handler exists when `setup_logging` runs - and is not the root's."""
    setup_logging()

    _access_line()

    line = uvicorn_access.getvalue()
    assert "GET /api/v1/embed/pk/generated/0123456789ab_image.png?[SECRET_REDACTED]" in line
    assert _LINK_TOKEN not in line
    assert '" 200' in line


def test_the_access_log_is_redacted_whatever_is_configured_after_setup(uvicorn_access):
    """A server that sets its handlers up after the app's startup still writes
    through the logger the filter is on."""
    logging.getLogger("uvicorn.access").filters.clear()
    setup_logging()
    access = logging.getLogger("uvicorn.access")
    for handler in access.handlers:
        handler.filters.clear()

    _access_line()

    assert _LINK_TOKEN not in uvicorn_access.getvalue()
    assert any(
        isinstance(f, PiiRedactionFilter) for f in logging.getLogger("uvicorn.error").filters
    )


def test_the_cli_sets_logging_up():
    from cli import commands

    with (
        patch.object(commands, "setup_logging") as configure,
        patch.object(commands, "cli") as cli,
    ):
        commands.main()

    configure.assert_called_once()
    cli.assert_called_once()


def test_one_line_writes_a_line_break_out_and_leaves_none_alone():
    """The call-site twin of the filter's escaping, for a value the static analyser
    would otherwise report as reaching a log line unsanitised."""
    assert one_line("https://a.example\r\nforged: entry") == "https://a.example\\r\\nforged: entry"
    assert one_line("plain") == "plain"
    assert one_line(None) is None
