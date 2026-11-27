"""The code a background step stores beside the English sentence of the refusal that stopped it.

Improve sessions and assistant requests keep the refusal's message for API clients and
the platform's own tools; the console words the code in the reader's language instead.
"""

from app.core.exceptions import (
    AppException,
    AuthenticationError,
    AuthorizationError,
    ConcurrentChangeError,
    ExternalServiceError,
    NotFoundError,
    PaymentRequiredError,
    RunExecutionError,
    RunFailedError,
    SystemAgentOutputError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.schemas.authoring import StepFailure

_UNAVAILABLE: dict[str, StepFailure] = {
    "not_seeded": "system_agent_not_seeded",
    "missing": "system_agent_missing",
    "unpublished": "system_agent_unpublished",
    "archived": "system_agent_archived",
    "no_access": "system_agent_no_access",
    "no_model": "system_agent_no_model",
}

# Refusals whose `details.reason` already says what to do, and means one thing
# wherever it is raised.
_REASONS: tuple[StepFailure, ...] = (
    "only_anonymised",
    "all_evidence",
    "no_scorer",
    "no_reruns",
    "evidence_too_large",
)


def failure_code(refusal: AppException) -> StepFailure:
    """The code for a refusal: its own reason when it is a known one, else its kind."""
    if isinstance(refusal, SystemAgentUnavailableError):
        return _UNAVAILABLE.get(refusal.reason, "refused")
    if isinstance(refusal, SystemAgentRunError | SystemAgentOutputError):
        return "system_agent_failed"
    reason = (refusal.details or {}).get("reason")
    known = next((code for code in _REASONS if code == reason), None)
    if known is not None:
        return known
    if isinstance(refusal, PaymentRequiredError):
        return "budget"
    if isinstance(refusal, NotFoundError):
        return "not_found"
    if isinstance(refusal, AuthenticationError | AuthorizationError):
        return "not_allowed"
    if isinstance(refusal, ConcurrentChangeError):
        return "changed"
    if isinstance(refusal, RunFailedError | RunExecutionError | ExternalServiceError):
        return "run_failed"
    return "refused" if refusal.status_code < 500 else "failed"
