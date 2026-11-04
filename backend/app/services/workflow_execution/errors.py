"""A caught `AppException` as a node's `WorkflowError`, and what no graph may route around.

Field for field - `WorkflowError` mirrors `AppException` on purpose - plus one
judgement made where the exception is caught: whether an `error.handle` may take
the failure over. A principal who is no longer allowed to do what the step does,
or whose spend is capped, is not a failure a fallback branch may paper over;
the run ends however the graph is wired. Everything else is the author's to
route.
"""

from app.core.exceptions import (
    AppException,
    AuthenticationError,
    AuthorizationError,
    PaymentRequiredError,
)
from app.workflows.contracts.results import WorkflowError

_NOT_BYPASSABLE: tuple[type[AppException], ...] = (
    AuthenticationError,
    AuthorizationError,
    PaymentRequiredError,
)


def workflow_error(exc: AppException, *, retryable: bool = False) -> WorkflowError:
    """`exc` as a node's typed failure."""
    return WorkflowError(
        code=exc.code,
        message=exc.message,
        details=exc.details or {},
        retryable=retryable,
        bypassable=not isinstance(exc, _NOT_BYPASSABLE),
    )
