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
import secrets
from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from starlette.datastructures import URL
from uvicorn.config import LOGGING_CONFIG
from uvicorn.logging import AccessFormatter, DefaultFormatter

from app.core.logging import (
    SECRET_PATH_MARKER,
    PiiRedactionFilter,
    redact_secret_paths,
    setup_logging,
)
from app.core.security import create_artifact_view_token

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
    # on the root and on any other logger, so snapshot them all - not just the one
    # this test adds - and restore, or a filter left on a persistent handler
    # redacts another test's assertions.
    touched = [*root.handlers]
    for logger in list(logging.Logger.manager.loggerDict.values()):
        if isinstance(logger, logging.Logger):
            touched.extend(logger.handlers)
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
    with a timestamp, a level and a message of the sender's choosing. The clearest
    way in is the rate limiter's `caller`, which can be the address somebody typed
    into a sign-in form (`py/log-injection`)."""
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


@pytest.fixture
def uvicorn_access(root_stream) -> Iterator[io.StringIO]:
    """`uvicorn.access` as uvicorn's own logging config leaves it: a handler of its
    own, uvicorn's access format, and `propagate` off - so the root's handlers, and
    whatever filters they carry, never see a request line."""
    logger = logging.getLogger("uvicorn.access")
    saved = (list(logger.handlers), logger.propagate, logger.level)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        AccessFormatter(fmt=LOGGING_CONFIG["formatters"]["access"]["fmt"], use_colors=False)
    )
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        logger.handlers, logger.propagate, logger.level = saved[0], saved[1], saved[2]


def _log_a_request(path: str) -> None:
    """The line uvicorn's HTTP protocol writes for every response, argument for argument."""
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "203.0.113.7:51234", "GET", path, "1.1", 200
    )


def _view_token() -> str:
    return create_artifact_view_token(uuid4(), expires_in=timedelta(minutes=5))


class TestSecretPaths:
    @pytest.mark.parametrize(
        ("address", "expected"),
        [
            ("/api/v1/artifact-content/{s}", "/api/v1/artifact-content/[REDACTED]"),
            ("/api/v1/artifact-embed/{s}", "/api/v1/artifact-embed/[REDACTED]"),
            ("/api/v1/public/artifacts/{s}", "/api/v1/public/artifacts/[REDACTED]"),
            (
                "/api/v1/public/artifacts/{s}/unlock?x=1",
                "/api/v1/public/artifacts/[REDACTED]/unlock?x=1",
            ),
            (
                "GET https://content.example/api/v1/artifact-content/{s} 200",
                "GET https://content.example/api/v1/artifact-content/[REDACTED] 200",
            ),
            ("/api/v1/conversations/shared/{s}", "/api/v1/conversations/shared/[REDACTED]"),
            ("/api/v1/public/workflow-forms/{s}", "/api/v1/public/workflow-forms/[REDACTED]"),
            ("/api/v1/workflow-webhook-tests/{s}", "/api/v1/workflow-webhook-tests/[REDACTED]"),
            (
                "/api/v1/workflows/0b6f3c1e-8a52-4d7e-9a43-2f1c5e7d9b10/webhook-test/{s}",
                "/api/v1/workflows/0b6f3c1e-8a52-4d7e-9a43-2f1c5e7d9b10/webhook-test/[REDACTED]",
            ),
            ("/api/v1/me/channel-link/{s}", "/api/v1/me/channel-link/[REDACTED]"),
            ("DELETE /api/v1/invitations/{s} 204", "DELETE /api/v1/invitations/[REDACTED] 204"),
            ("/api/v1/invitations/{s}/accept", "/api/v1/invitations/[REDACTED]/accept"),
            (
                "/api/v1/workflow-resume/0b6f3c1e-8a52-4d7e-9a43-2f1c5e7d9b10/{s}",
                "/api/v1/workflow-resume/0b6f3c1e-8a52-4d7e-9a43-2f1c5e7d9b10/[REDACTED]",
            ),
        ],
    )
    def test_the_credential_segment_of_every_secret_bearing_address_is_replaced(
        self, address, expected
    ):
        assert redact_secret_paths(address.format(s=secrets.token_urlsafe(32))) == expected

    @pytest.mark.parametrize(
        "address",
        [
            # A static file under the content route.
            "/api/v1/artifact-content/lib/chart.umd.min.js",
            # An artifact's id in the members' own routes.
            f"/api/v1/artifacts/0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f/view",
            # A conversation's id, and the list of conversations shared with the caller.
            f"/api/v1/conversations/0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f",
            "/api/v1/conversations/shared-with-me",
            # Opening a webhook test names only the workflow.
            f"/api/v1/workflows/0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f/webhook-test",
            # The identity a DELETE unlinks, and the list of linked accounts.
            f"/api/v1/me/channel-link/0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f",
            "/api/v1/me/channel-link",
            # Staging and redeeming an invitation's handle carry no token in the path,
            # and an administrator lists, creates and revokes by the organization's
            # and the invitation's ids.
            "/api/v1/invitations/stage",
            "/api/v1/invitations/staged/accept",
            f"/api/v1/orgs/0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f/invitations?status=pending",
            f"/api/v1/orgs/0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f/invitations/link",
            f"/api/v1/orgs/0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f/invitations/7e2d1c9b-3f4a-4b5c-8d6e-1a2b3c4d5e6f",
            # A run's own routes name only the run.
            f"/api/v1/workflow-runs/0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f/events",
            # Signed calls name an exposure, and a widget's key is public by design.
            f"/api/v1/workflow-webhooks/0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f",
            f"/api/v1/workflow-github/0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f",
            "/api/v1/embed/pk_live_widget/ws",
            # A route template, as a span name or `http.route` carries it.
            "GET /api/v1/public/workflow-forms/{token}",
            "/api/v1/workflows/{workflow_id}/webhook-test/{token}",
            "/api/v1/invitations/{token}/accept",
            "/api/v1/workflow-resume/{run_id}/{token}",
        ],
    )
    def test_an_address_with_nothing_secret_in_it_is_left_alone(self, address):
        assert redact_secret_paths(address) == address

    def test_the_filter_writes_the_marker_whatever_the_token_looks_like(self):
        """Before the JWT pattern gets to it, so a view token and a public link key
        come out the same."""
        assert (
            PiiRedactionFilter()._redact(f"/api/v1/artifact-content/{_view_token()}")
            == f"/api/v1/artifact-content/{SECRET_PATH_MARKER}"
        )


@pytest.mark.security
def test_uvicorn_s_access_log_does_not_write_an_artifact_s_address(uvicorn_access):
    """Every load of a page wrote its signed address to stdout, and every request
    to a public link its key: the access log has a handler of its own, so the
    filter on the root's handlers never ran on it."""
    token, key = _view_token(), secrets.token_urlsafe(24)
    setup_logging()

    _log_a_request(f"/api/v1/artifact-content/{token}")
    _log_a_request(f"/api/v1/public/artifacts/{key}/unlock")

    emitted = uvicorn_access.getvalue()
    assert token not in emitted and key not in emitted
    assert '"GET /api/v1/artifact-content/[REDACTED] HTTP/1.1" 200' in emitted
    assert "/api/v1/public/artifacts/[REDACTED]/unlock" in emitted


@pytest.mark.anyio
async def test_the_lifespan_covers_a_server_that_configured_logging_after_the_import(
    monkeypatch, uvicorn_access
):
    """`agenticos server run` imports `app.main` - which runs `setup_logging` -
    before uvicorn builds its loggers, so only the lifespan's call reaches them."""
    from app import main
    from tests.test_lifespan_drain import _stub_startup

    _stub_startup(monkeypatch)
    token = _view_token()

    async with main.lifespan(FastAPI()):
        _log_a_request(f"/api/v1/artifact-content/{token}")

    assert token not in uvicorn_access.getvalue()
    assert "/api/v1/artifact-content/[REDACTED]" in uvicorn_access.getvalue()


class _LoggerThatSpawnsAnother(logging.Logger):
    """A logger whose handlers are read while another thread calls `getLogger`.

    Reading `handlers` adds a logger to `loggerDict`, which is what a thread doing
    so in the middle of `setup_logging`'s walk would do - deterministically."""

    @property
    def handlers(self) -> list[logging.Handler]:
        logging.getLogger(f"spawned.{uuid4().hex}")
        return []

    @handlers.setter
    def handlers(self, _value: list[logging.Handler]) -> None:
        pass


def test_a_logger_created_during_setup_does_not_break_it(root_stream):
    """`setup_logging` walks every logger; one added by another thread meanwhile
    raised `dictionary changed size during iteration` out of the lifespan."""
    manager = logging.Logger.manager
    name = f"spawning.{uuid4().hex}"
    manager.loggerDict[name] = _LoggerThatSpawnsAnother(name)
    before = set(manager.loggerDict)
    try:
        setup_logging()
    finally:
        for added in set(manager.loggerDict) - before | {name}:
            manager.loggerDict.pop(added, None)


class TestSecretQueries:
    @pytest.mark.parametrize(
        ("address", "expected"),
        [
            (
                "/api/v1/embed/pk_live_widget/ws?visitor={s}",
                "/api/v1/embed/pk_live_widget/ws?visitor=[REDACTED]",
            ),
            (
                "/api/v1/embed/pk_live_widget/ws?token={s}",
                "/api/v1/embed/pk_live_widget/ws?token=[REDACTED]",
            ),
            (
                "/api/v1/oauth/google/callback?state={s}&code={s}&scope=openid",
                "/api/v1/oauth/google/callback?state=[REDACTED]&code=[REDACTED]&scope=openid",
            ),
            (
                "/api/v1/oauth/oidc/login?invitation_handle={s}&client=desktop",
                "/api/v1/oauth/oidc/login?invitation_handle=[REDACTED]&client=desktop",
            ),
            (
                "/api/v1/auth/kerberos/login?client=desktop&invitation_handle={s}",
                "/api/v1/auth/kerberos/login?client=desktop&invitation_handle=[REDACTED]",
            ),
            # The console's pages an email or a sign-in sends the browser to.
            ("/reset-password?token={s}", "/reset-password?token=[REDACTED]"),
            ("/auth/magic-link?token={s}#top", "/auth/magic-link?token=[REDACTED]#top"),
            (
                "/auth/callback?code={s}&desktop_nonce=n1",
                "/auth/callback?code=[REDACTED]&desktop_nonce=n1",
            ),
            # A span's `url.query` has no `?` in front of it.
            ("visitor={s}&token={s}", "visitor=[REDACTED]&token=[REDACTED]"),
            # A value that opens with a percent-encoded byte is not a `%d` placeholder.
            (
                "/api/v1/oauth/google/callback?code=%d3{s}&state=%DF{s}",
                "/api/v1/oauth/google/callback?code=[REDACTED]&state=[REDACTED]",
            ),
            (
                'GET "https://api.example/api/v1/embed/k/ws?token={s}" 101',
                'GET "https://api.example/api/v1/embed/k/ws?token=[REDACTED]" 101',
            ),
        ],
    )
    def test_the_value_of_every_credential_query_parameter_is_replaced(self, address, expected):
        assert redact_secret_paths(address.format(s=secrets.token_urlsafe(32))) == expected

    @pytest.mark.parametrize(
        "address",
        [
            "/api/v1/agents?q=support&skip=50&limit=25",
            f"/api/v1/artifacts/0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f/view?version_id=7e2d1c9b-3f4a-4b5c-8d6e-1a2b3c4d5e6f",
            f"/ws/agent?organization_id=0b3c8f4e-6a1d-4c2e-9f7a-5d8e1b2c3a4f",
            "/api/v1/oauth/oidc/login?client=desktop&desktop_nonce=3f1c",
            "/api/v1/tables/t/records?sort=created_at&direction=desc",
            # A name that only ends in one of the credential names is another parameter.
            "/x?access_token_hint=1&postcode=00-950&mystate=on",
            # Not after `?` or `&`: prose, not a query string.
            "the run moved to state=running",
        ],
    )
    def test_an_ordinary_query_parameter_is_left_alone(self, address):
        assert redact_secret_paths(address) == address

    def test_a_placeholder_in_a_format_string_is_left_for_its_argument(self, root_stream):
        """Redacting `%s` in `msg` would leave `args` with nothing to fill, and the
        record would fail to format and be dropped."""
        setup_logging()

        logging.getLogger("test.query").warning("state=%s token=%s", "open", "x")

        assert "state=open token=x" in root_stream.getvalue()

    def test_a_number_placeholder_is_left_for_its_argument(self, root_stream):
        setup_logging()

        logging.getLogger("test.query").warning("code=%d attempts", 3)

        assert "code=3 attempts" in root_stream.getvalue()

    @pytest.mark.security
    def test_an_address_passed_as_an_object_is_redacted_as_it_renders(self, root_stream):
        """`%s` renders a `URL` through `str()`, after the filter ran; a filter that
        only looked at string arguments let the query through whole."""
        state = secrets.token_urlsafe(32)
        setup_logging()

        logging.getLogger("test.query").warning(
            "callback %s", URL(f"https://api.example/api/v1/oauth/google/callback?state={state}")
        )

        emitted = root_stream.getvalue()
        assert state not in emitted
        assert "callback?state=[REDACTED]" in emitted

    def test_an_ordinary_object_argument_formats_as_before(self, root_stream):
        setup_logging()

        logging.getLogger("test.query").warning("ids %r and %s", (1, 2), uuid4().__class__.__name__)

        assert "ids (1, 2) and UUID" in root_stream.getvalue()


@pytest.fixture
def uvicorn_error(root_stream) -> Iterator[io.StringIO]:
    """`uvicorn` as uvicorn's own logging config leaves it: the `default` handler and
    format, `propagate` off - with `uvicorn.error`, the logger the WebSocket
    protocols write through, propagating into it."""
    parent, error = logging.getLogger("uvicorn"), logging.getLogger("uvicorn.error")
    saved = (list(parent.handlers), parent.propagate, parent.level, error.propagate, error.level)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        DefaultFormatter(fmt=LOGGING_CONFIG["formatters"]["default"]["fmt"], use_colors=False)
    )
    parent.handlers = [handler]
    parent.propagate = False
    parent.setLevel(logging.INFO)
    error.propagate = True
    error.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        parent.handlers, parent.propagate, error.propagate = saved[0], saved[1], saved[3]
        parent.setLevel(saved[2])
        error.setLevel(saved[4])


@pytest.mark.security
def test_uvicorn_s_websocket_line_does_not_write_the_widget_s_credentials(uvicorn_error):
    """uvicorn logs every accepted socket with its path and query - the hosted
    widget's continuity key and the customer's signed token among them - through
    `uvicorn.error`, whose handler is on `uvicorn`, not on the root."""
    visitor, token = secrets.token_hex(16), _view_token()
    setup_logging()

    # Argument for argument what `websockets_impl.py`, `websockets_sansio_impl.py`
    # and `wsproto_impl.py` write on `websocket.accept`.
    logging.getLogger("uvicorn.error").info(
        '%s - "WebSocket %s" [accepted]',
        "203.0.113.7:51234",
        f"/api/v1/embed/pk_live_widget/ws?visitor={visitor}&token={token}",
    )

    emitted = uvicorn_error.getvalue()
    assert visitor not in emitted and token not in emitted
    assert (
        '"WebSocket /api/v1/embed/pk_live_widget/ws?visitor=[REDACTED]&token=[REDACTED]" [accepted]'
        in emitted
    )


@pytest.mark.security
def test_uvicorn_s_access_log_does_not_write_a_sign_in_s_code(uvicorn_access):
    """The provider's return is an ordinary GET, so its code and state are in the
    access line's path."""
    code, state = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    setup_logging()

    _log_a_request(f"/api/v1/oauth/google/callback?code={code}&state={state}")

    emitted = uvicorn_access.getvalue()
    assert code not in emitted and state not in emitted
    assert (
        '"GET /api/v1/oauth/google/callback?code=[REDACTED]&state=[REDACTED] HTTP/1.1" 200'
        in emitted
    )
