"""Application exceptions.

Domain exceptions with HTTP status codes for the hybrid approach.
These exceptions are caught by exception handlers and converted to proper HTTP responses.
"""

from typing import Any


class AppException(Exception):
    """Base exception for all application errors.

    Attributes:
        message: Human-readable error message.
        code: Machine-readable error code for clients.
        status_code: HTTP status code to return.
        details: Additional error details (e.g., field names, IDs). `None` when not provided.
    """

    message: str = "An error occurred"
    code: str = "APP_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: str | None = None,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.message = message or self.__class__.message
        self.code = code or self.__class__.code
        self.details = details
        super().__init__(self.message)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, code={self.code!r})"


class NotFoundError(AppException):
    """Resource not found (404)."""

    message = "Resource not found"
    code = "NOT_FOUND"
    status_code = 404


class AlreadyExistsError(AppException):
    """Resource already exists (409)."""

    message = "Resource already exists"
    code = "ALREADY_EXISTS"
    status_code = 409


class ValidationError(AppException):
    """Validation error (422)."""

    message = "Validation error"
    code = "VALIDATION_ERROR"
    status_code = 422


class ExportTooLargeError(AppException):
    """A bulk export matched more rows than one request may return (413).

    The honest half of a row cap: an export with no ceiling either streams the
    whole table down a held connection or truncates silently, and a truncated
    CSV is worse than a refused one because a spreadsheet sums whatever arrives.
    So the request is refused above the cap rather than trimmed to it, and the
    message names the ceiling and tells the caller to narrow the date range -
    the one control that actually shrinks the match. `details` carries the two
    numbers, never the rows themselves.
    """

    message = "The export matched too many rows"
    code = "EXPORT_TOO_LARGE"
    status_code = 413


class AuthenticationError(AppException):
    """Authentication failed (401)."""

    message = "Authentication failed"
    code = "AUTHENTICATION_ERROR"
    status_code = 401


class AuthorizationError(AppException):
    """Authorization failed - insufficient permissions (403)."""

    message = "Insufficient permissions"
    code = "AUTHORIZATION_ERROR"
    status_code = 403


class RateLimitError(AppException):
    """Rate limit exceeded (429)."""

    message = "Rate limit exceeded"
    code = "RATE_LIMIT_EXCEEDED"
    status_code = 429


class BadRequestError(AppException):
    """Bad request (400)."""

    message = "Bad request"
    code = "BAD_REQUEST"
    status_code = 400


class PaymentRequiredError(AppException):
    """Payment required - seat or usage limit reached (402)."""

    message = "Payment required"
    code = "PAYMENT_REQUIRED"
    status_code = 402


class ExternalServiceError(AppException):
    """External service unavailable (503)."""

    message = "External service unavailable"
    code = "EXTERNAL_SERVICE_ERROR"
    status_code = 503


class ConfigurationError(AppException):
    """A feature the deployment has not been configured for (503).

    Distinct from :class:`ExternalServiceError`, which says an upstream we do
    have credentials for is down, and from :class:`BadRequestError`, which
    blames the caller. This one is nobody's mistake but the operator's, so the
    message must name the setting to change rather than describing a symptom -
    a missing credential surfacing as a 500 from inside a vendor SDK is the
    failure this class exists to stop.
    """

    message = "This feature is not configured"
    code = "CONFIGURATION_ERROR"
    status_code = 503


class RunExecutionError(AppException):
    """A run failed while executing, its terminal status already recorded (500).

    Raised by :meth:`~app.services.agent_runner.AgentRunnerService.resume` when the
    continuation of a parked run *itself* raises. `AgentRunnerService._run` has by
    then recorded the run `failed` (or `cancelled`) and committed it, so the failure
    is durable and this does not swallow it - the caller still gets a 5xx. What it
    adds is the recorded status in `details`: the resume answer is the only place a
    web-chat surface learns a delegate's outcome (the continuation ran over HTTP, not
    the socket the conversation streams), and the raising path used to discard that
    answer - leaving a panel waiting on a decision already spent and a run that can no
    longer be resumed (agenticos#262). The original exception is chained, and `_run`
    has already logged it; the message here stays generic for the same reason the
    unhandled-exception handler's does - a raw run error is not a thing to put on the
    wire.
    """

    message = "The run failed while continuing after approval"
    code = "RUN_EXECUTION_FAILED"
    status_code = 500


class DatabaseError(AppException):
    """Database error (500)."""

    message = "Database error"
    code = "DATABASE_ERROR"
    status_code = 500


class InternalError(AppException):
    """Internal server error (500)."""

    message = "Internal server error"
    code = "INTERNAL_ERROR"
    status_code = 500
