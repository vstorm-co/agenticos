"""Logfire observability configuration."""

from typing import Any

import logfire

from app.core.config import settings
from app.core.otel_compat import patch_route_details

WORKER_SERVICE_SUFFIX = "-worker"


def setup_logfire(*, service_name: str | None = None) -> None:
    """Configure Logfire instrumentation.

    `service_name` overrides the deployment's own for a process that is not the
    API, so one project can tell them apart.
    """
    logfire.configure(
        token=settings.LOGFIRE_TOKEN,
        service_name=service_name or settings.LOGFIRE_SERVICE_NAME,
        environment=settings.LOGFIRE_ENVIRONMENT,
        send_to_logfire="if-token-present",
    )


def setup_worker_observability() -> None:
    """Configure Logfire in a flow process, which is not the one that starts it.

    `serve()` runs each flow in its own subprocess: it imports the flow's module
    and never ran the startup the API's lifespan does, which is the same reason
    `setup_logging` is called inside a flow rather than once in
    `prefect_app.main` (#440). So a deployment-wide `LOGFIRE_TOKEN` traced every
    run the API served and no scheduled one, and a fired run's
    `logfire_trace_id` was null because nothing was tracing for
    `current_trace_id` to read (#1700).

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
    logfire.instrument_fastapi(app)


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
