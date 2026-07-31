"""Exception handlers for FastAPI application.

These handlers convert domain exceptions to proper HTTP responses.
WebSocket connections that raise an `AppException` before `accept()` are
handled too - Starlette closes the socket with 403 and we just log the
incident; we cannot return an HTTP body for a non-HTTP scope.

Everything a client can be refused with leaves here in one shape::

    {"error": {"code": ..., "message": ..., "details": ...}}

including schema validation, which FastAPI would otherwise answer in its own
`{"detail": [...]}` format. Two shapes on the wire means every caller either
handles both or silently mishandles one, and the one it mishandles is the one
that carries the field names a form needs.
"""

import logging
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import HTTPConnection

from app.agents.capabilities.budget import BudgetExceeded
from app.core.exceptions import AppException, ValidationError

logger = logging.getLogger(__name__)

# Where a validation error came from, as Pydantic reports it in the first
# element of `loc`. Nothing a form can act on, so it is dropped from the path.
_LOCATIONS = frozenset({"body", "query", "path", "header", "cookie"})


def _connection_meta(conn: HTTPConnection) -> dict[str, Any]:
    """Common log fields shared by HTTP requests and WebSocket connections.

    `method` exists only on HTTP `Request` - for WebSockets we surface the
    scope type so log filters can still distinguish the two.
    """
    return {
        "path": conn.url.path,
        "method": getattr(conn, "method", None) or conn.scope.get("type", "unknown"),
    }


def _is_websocket(conn: HTTPConnection) -> bool:
    return conn.scope.get("type") == "websocket"


async def app_exception_handler(request: HTTPConnection, exc: AppException) -> JSONResponse | None:
    """Handle application exceptions for both HTTP and WebSocket scopes.

    Logs 5xx errors as errors and 4xx as warnings. Returns a JSON response
    for HTTP scopes; returns `None` for WebSocket scopes (Starlette will
    close the socket on its own).
    """
    log_extra = {
        "error_code": exc.code,
        "status_code": exc.status_code,
        "details": exc.details,
        **_connection_meta(request),
    }

    if exc.status_code >= 500:
        logger.error("%s: %s", exc.code, exc.message, extra=log_extra)
    else:
        logger.warning("%s: %s", exc.code, exc.message, extra=log_extra)

    if _is_websocket(request):
        return None

    headers: dict[str, str] = {}
    if exc.status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
        headers=headers,
    )


def _field_path(location: Sequence[str | int]) -> str:
    """The dotted path of the field a validation error is about.

    Pydantic reports where the value came from as well as where it sits -
    `("body", "spec", "name")`. A form can do nothing with "body", so it is
    dropped and the rest joined: `spec.name`. List indices stay in the path,
    because "the third capability" is exactly what the reader needs to know.
    """
    parts = list(location)
    if parts and parts[0] in _LOCATIONS:
        parts = parts[1:]
    return ".".join(str(part) for part in parts) or "request"


def _summarize(fields: list[dict[str, str]]) -> str:
    """One line for a client with nowhere better to put it than a toast.

    The structured list is what a form should render; this is the fallback, so
    it names the fields rather than saying that something was invalid.
    """
    if len(fields) == 1:
        return f"{fields[0]['field']}: {fields[0]['message']}"
    return "Some fields need fixing: " + ", ".join(field["field"] for field in fields)


async def validation_exception_handler(
    request: HTTPConnection, exc: RequestValidationError
) -> JSONResponse | None:
    """Answer a schema-validation failure in the application's error envelope.

    Every problem is reported, not just the first, and each one carries the
    field it belongs to - that is what lets the UI mark the offending input
    instead of showing a sentence about a form the reader has to re-scan.
    """
    fields = [
        {"field": _field_path(error["loc"]), "message": error["msg"]} for error in exc.errors()
    ]
    return await app_exception_handler(
        request,
        ValidationError(message=_summarize(fields), details={"fields": fields}),
    )


async def budget_exceeded_handler(
    request: HTTPConnection, exc: BudgetExceeded
) -> JSONResponse | None:
    """A budget refusal is the platform working, not the platform broken.

    `BudgetExceeded` is not an `AppException` - it is raised inside agent runs,
    where each surface records it as the run's outcome. But a request refused
    *before* any work started - a document upload against a spent monthly cap -
    lets it reach HTTP, and answering 500 would tell the operator something
    crashed when the correct reading is "raise the limit or wait for the first
    of the month".
    """
    if _is_websocket(request):
        logger.warning("BUDGET_EXCEEDED: %s", exc, extra=_connection_meta(request))
        return None

    return JSONResponse(
        status_code=402,
        content={
            "error": {
                "code": "BUDGET_EXCEEDED",
                "message": str(exc),
                "details": {
                    "scope": exc.scope,
                    "limit_usd": str(exc.limit_usd),
                    "spent_usd": str(exc.spent_usd),
                },
            }
        },
    )


async def unhandled_exception_handler(
    request: HTTPConnection, exc: Exception
) -> JSONResponse | None:
    """Handle unexpected exceptions.

    Logs the full exception but returns a generic error to the client
    to avoid leaking sensitive information.
    """
    logger.exception("Unhandled exception", extra=_connection_meta(request))

    if _is_websocket(request):
        return None

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": None,
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app.

    Call this after creating the FastAPI application instance.
    """
    # Handler returns None for WebSocket connections (no JSONResponse there),
    # which Starlette's HTTP-handler type doesn't model.
    app.add_exception_handler(AppException, app_exception_handler)  # ty: ignore[invalid-argument-type]
    app.add_exception_handler(BudgetExceeded, budget_exceeded_handler)  # ty: ignore[invalid-argument-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # ty: ignore[invalid-argument-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)  # ty: ignore[invalid-argument-type]
