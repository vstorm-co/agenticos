"""Logfire observability configuration."""

from typing import Any

import logfire
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.trace import Span
from starlette.requests import HTTPConnection

from app import __version__
from app.core.config import settings
from app.core.logging import SECRET_PATH_MARKER, SECRET_QUERY_PARAMS, redact_secret_paths
from app.core.otel_compat import patch_route_details

WORKER_SERVICE_SUFFIX = "-worker"


def setup_logfire(*, service_name: str | None = None) -> None:
    """Configure Logfire instrumentation.

    `service_name` overrides the deployment's own for a process that is not the
    API, so one project can tell them apart.

    `SecretPathRedactionProcessor` goes in as an additional processor because
    Logfire runs those first, ahead of the processor that copies every span into a
    pending one the moment it starts (`logfire/_internal/config.py`,
    `_initialize`). That copy goes to the console and the OTLP exporters, so a
    span has to be clean at start, not just by the time it ends.

    Production prints no spans. The console exporter writes one line per SQL and
    Redis call - about forty per request - into a container log that is read by
    `docker compose logs`, where nobody can query them and every real error is
    buried (#2228). Spans belong in Logfire; `doctor` says when no token sends
    them anywhere. Elsewhere the console stays on, because a developer watching
    the server is exactly who those lines are for.
    """
    logfire.configure(
        token=settings.LOGFIRE_TOKEN,
        service_name=service_name or settings.LOGFIRE_SERVICE_NAME,
        environment=settings.LOGFIRE_ENVIRONMENT,
        service_version=__version__,
        send_to_logfire="if-token-present",
        additional_span_processors=[SecretPathRedactionProcessor()],
        console=False if settings.ENVIRONMENT == "production" else None,
    )


def setup_worker_observability() -> None:
    """Configure Logfire in the worker, which never runs the API's lifespan.

    `python -m app.worker` calls this once on start, beside `setup_logging`
    (#440). Without it a deployment-wide `LOGFIRE_TOKEN` traced every run the API
    served and no scheduled one, and a fired run's `logfire_trace_id` was null
    because nothing was tracing for `current_trace_id` to read (#1700).

    The service name carries a suffix so one project can separate them. A slow
    scheduled run and a slow chat turn are different problems, and a dashboard
    that cannot tell them apart is useful for neither.

    An agent with its own `observability` token was never affected here:
    `instrument_agent` configures an instance of its own, per agent, wherever the
    run executes.
    """
    setup_logfire(service_name=f"{settings.LOGFIRE_SERVICE_NAME}{WORKER_SERVICE_SUFFIX}")
    instrument_pydantic_ai()


def instrument_app(app: Any) -> None:
    """Instrument FastAPI app with Logfire.

    The compatibility patch goes on first, before anything captures the helper it
    replaces: without it every wrong-method request to this API answered 500
    instead of 405. `app/core/otel_compat.py` has the whole of why.
    """
    patch_route_details()
    logfire.instrument_fastapi(
        app,
        request_attributes_mapper=redact_secret_arguments,
        server_request_hook=redact_span_addresses,
    )


class SecretPathRedactionProcessor(SpanProcessor):
    """Takes a credential in an address - path segment or query value - out of every span at start.

    The ASGI instrumentation starts the request span with the path, the query and
    the full URL already set (`http.target`, `http.url`, `url.path`, `url.query`,
    `url.full`), and Logfire's
    own scrubber treats those keys as safe and never looks inside them. Logfire
    then copies the span at start into a pending span, which the console exporter
    prints to stdout - past every logging filter - and the OTLP exporter can send
    on its own. Redacting at start is the only point that comes before that copy.
    """

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        """Redact the span before the pending-span processor copies it."""
        _redact_span(span)


def redact_span_addresses(span: Span, _scope: dict[str, Any]) -> None:
    """Redact the request span again after the ASGI middleware has set its attributes.

    The middleware starts the span with its attributes, which
    `SecretPathRedactionProcessor` redacts, and then sets each of them again on the
    started span - so the raw address is back on the span that ends and is exported.
    This hook runs after that second write.
    """
    _redact_span(span)


def _redact_span(span: Span) -> None:
    """Replace each credential `redact_secret_paths` finds in the span's name and string attributes.

    Every string attribute is checked rather than a list of keys, because which of
    them exist depends on the semantic-convention mode. The name is the route
    template, or the raw path when no route matched in full; `app/core/otel_compat.py`
    redacts that path for the request span, and this covers any other span.
    """
    if not isinstance(span, ReadableSpan):
        return
    redacted = {
        key: clean
        for key, value in (span.attributes or {}).items()
        if isinstance(value, str) and (clean := redact_secret_paths(value)) != value
    }
    if redacted:
        span.set_attributes(redacted)
    name = redact_secret_paths(span.name)
    if name != span.name:
        span.update_name(name)


def redact_secret_arguments(request: HTTPConnection, attributes: dict[str, Any]) -> dict[str, Any]:
    """Logfire's record of an endpoint's arguments, without a credential from the address.

    Logfire attaches the parsed arguments to the request span, so the content
    route's `token`, a public link's `public_key`, and a form's, a share's, an
    invitation's or a resume link's `token` arrive there as values, under names its
    scrubber does not consider secret - and so do the widget socket's `visitor` and
    `token` and a sign-in's `invitation_handle`, from the query. A path parameter
    whose value `redact_secret_paths` took out of the path is replaced with the same
    marker; one it left, such as the `workflow_id` before `/webhook-test/<token>` or
    the `run_id` before a resume token, is kept. A query parameter is replaced when
    its name is one of `SECRET_QUERY_PARAMS`, and every other one - `client`, `q`,
    `limit` - is kept. The mapping it was handed is copied, not changed, as Logfire
    requires.
    """
    secret = {name for name in request.query_params if name in SECRET_QUERY_PARAMS}
    path = request.url.path
    redacted = redact_secret_paths(path)
    if redacted != path:
        kept = set(redacted.split("/"))
        secret.update(name for name, value in request.path_params.items() if str(value) not in kept)
    if not secret:
        return attributes
    values = {
        name: SECRET_PATH_MARKER if name in secret else value
        for name, value in attributes["values"].items()
    }
    redacted_attributes = {**attributes, "values": values}
    if attributes.get("errors"):
        # A credential that failed validation - a `visitor` too long, say - reaches
        # the span as the error's `input` instead of as a value.
        redacted_attributes["errors"] = [
            {**error, "input": SECRET_PATH_MARKER}
            if isinstance(error, dict) and error.get("loc") and error["loc"][-1] in secret
            else error
            for error in attributes["errors"]
        ]
    return redacted_attributes


def instrument_asyncpg() -> None:
    """Instrument asyncpg for PostgreSQL."""
    logfire.instrument_asyncpg()


def instrument_redis() -> None:
    """Instrument Redis."""
    logfire.instrument_redis()


def instrument_httpx() -> None:
    """Instrument HTTPX for outgoing HTTP requests."""
    logfire.instrument_httpx()


def instrument_pydantic_ai() -> None:
    """Instrument PydanticAI for AI agent observability."""
    logfire.instrument_pydantic_ai()
