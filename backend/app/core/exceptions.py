"""Application exceptions.

Domain exceptions with HTTP status codes for the hybrid approach.
These exceptions are caught by exception handlers and converted to proper HTTP responses.
"""

from typing import Any
from uuid import UUID


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


class ConcurrentChangeError(AppException):
    """Something this operation had to hold was held by another transaction (409).

    Nothing was written: the attempt stopped at the point it could no longer be
    made safe, and what made it unsafe is transient by construction. The caller
    retries.
    """

    message = "Another change to this resource is in flight. Try again."
    code = "CONCURRENT_CHANGE"
    status_code = 409


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


class RunFailedError(AppException):
    """A run started over the API failed, its terminal status already recorded (500).

    `AgentRunnerService._run` records the run `failed` with our own sentence for
    why (`run_failure_summary`) and commits before re-raising, so the run exists and
    can be read. The unhandled-exception handler answered that as a bare 500 with
    no details, and the caller never learnt the id of the run it had just paid for
    (#2121). This carries it: `details.run_id` and `details.status`, and the
    recorded reason in the message - never the raw exception, which can hold a
    provider's request URL.
    """

    message = "The run failed"
    code = "RUN_FAILED"
    status_code = 500


class ModelCallFailedError(RunFailedError):
    """The model provider refused or failed a run's request (502).

    Its own status because it is somebody else's failure: the request reached the
    provider and the provider answered with an error, so a retry later - or a
    different model - may well succeed where retrying our own bug would not.
    """

    message = "The model provider did not complete the request"
    code = "MODEL_CALL_FAILED"
    status_code = 502


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


class AiAssistanceDisabledError(AuthorizationError):
    """The organization has switched AI assistance off (403).

    Raised by the service that would start a model-backed eval or authoring run -
    the judge, the case generator, the authoring assistant - so the switch holds
    whichever client asks. Its own `code`, so a caller that degrades rather than
    refuses tells it apart from a missing permission.
    """

    message = "AI assistance is switched off for this organization"
    code = "AI_ASSISTANCE_OFF"


class SystemAgentUnavailableError(BadRequestError):
    """A system agent cannot run for this caller (400).

    `reason` says why - `not_seeded`, `missing` (the agent picked for the job is
    gone), `unpublished`, `archived`, `no_access` or `no_model` - because each has
    a different fix, and a person told only "unavailable" cannot tell whether to
    pick a model or ask for a grant.
    """

    message = "This system agent cannot run"
    code = "SYSTEM_AGENT_UNAVAILABLE"

    def __init__(self, message: str, *, key: str, reason: str) -> None:
        super().__init__(message=message, details={"key": key, "reason": reason})
        self.reason = reason


class SystemAgentRestrictedError(BadRequestError):
    """A system agent was asked to do what only an ordinary agent does (400).

    A system agent runs for the platform - the eval judge grades scores - and
    only through the system agent runner. It is never chatted with, exposed on a
    channel, embedded, scheduled or delegated to. `action` names what was refused.
    """

    message = "This is a system agent"
    code = "SYSTEM_AGENT_RESTRICTED"

    def __init__(self, *, name: str, agent_id: UUID, action: str) -> None:
        super().__init__(
            message=(
                f"'{name}' is a system agent: the platform runs it, so it cannot be "
                f"used for {action}."
            ),
            details={"agent_id": agent_id, "action": action},
        )
        self.action = action


class SystemAgentRunError(BadRequestError):
    """A system agent's run ended without an answer to read (400).

    The run is recorded either way - a budget refusal, a guardrail block, a
    failure - and `run_id` names it, so the spend and the error stay in Activity.
    `status` is the run's terminal status.
    """

    message = "The system agent's run did not complete"
    code = "SYSTEM_AGENT_RUN_FAILED"

    def __init__(self, message: str, *, run_id: UUID, status: str) -> None:
        super().__init__(message=message, details={"run_id": run_id, "status": status})
        self.run_id = run_id
        self.status = status


class SystemAgentOutputError(BadRequestError):
    """A system agent answered, but not in the shape its caller asked for (400).

    Not retried: a second call costs as much as the first and an edited prompt
    that broke the format breaks it again. `run_id` names the recorded run;
    `answer` is what the agent answered, for the caller to show, never placed in
    `details`.
    """

    message = "The system agent's answer could not be read"
    code = "SYSTEM_AGENT_OUTPUT_INVALID"

    def __init__(self, message: str, *, run_id: UUID, answer: str = "") -> None:
        super().__init__(message=message, details={"run_id": run_id})
        self.run_id = run_id
        self.answer = answer


class NothingToScoreError(BadRequestError):
    """No configured scorer has anything to check on a case (400).

    Raised before anything is kept or the judge is called, so an eval run can
    count the case as undecided rather than failed.
    """

    message = "Nothing to score: the dataset's scorers check nothing this case expects"
    code = "NOTHING_TO_SCORE"

    def __init__(self, *, case_id: UUID) -> None:
        super().__init__(details={"case_id": case_id})
        self.case_id = case_id


class PromotionBlockedError(AppException):
    """An environment's eval suites have not all passed on the version (409).

    `details.gate` is the whole gate as `PromotionGateRead` - each guard, its
    state and the result behind it - so a console can say which suite stopped
    the promotion, offer to run it, and offer an override where it may.
    """

    message = "This version has not passed the evals that guard the environment"
    code = "PROMOTION_BLOCKED"
    status_code = 409


class EvalSuiteInUseError(AppException):
    """An eval suite guards an environment, so it cannot be deleted (409).

    `details.environments` names them: the suite comes off each first.
    """

    message = "This eval suite guards an environment"
    code = "EVAL_SUITE_IN_USE"
    status_code = 409


class EvalSuiteNotRunnableError(AppException):
    """An eval suite cannot run now - it is paused, or already running (409).

    `details.reason` is `paused` or `running`, each with its own fix.
    """

    message = "This eval suite cannot run now"
    code = "EVAL_SUITE_NOT_RUNNABLE"
    status_code = 409
