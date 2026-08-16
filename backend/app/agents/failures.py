"""The one sentence a stored failure may hold, for exceptions it may not.

`run_failure_summary` began life in `app.services.agent_runner` (#676), which put
it out of the capability layer's reach - and a delegated run's row is composed
there, from the handle the subagents library settles. It lives here so both
layers write the same sentence for the same failure (#699).
"""

from pydantic_ai.exceptions import ModelHTTPError

from app.core.exceptions import AppException


def run_failure_summary(exc: BaseException) -> str:
    """The sentence a failed run may store, for an exception it may not.

    `agent_runs.error` used to hold `str(exc)` of whatever came out of the run.
    It is a stored column on `AgentRunRead`, rendered in run history to every
    member who can read it, and what raises there is a model client with `httpx`
    underneath - so that routinely meant an endpoint, an internal host, or a URL
    with a key still in its query string, sitting in a row somebody opens weeks
    later. Same rule as #342 in an HTTP body, #423 in the ingestion columns and
    #659 in the chat frame, with the longest life of the four (#676). A
    delegated run's row takes it through `TaskHandle.exception`, which is why
    the parameter is `BaseException` - that is what the library's retry
    callback receives (#699).

    Ours is kept whole. An `AppException` raised inside the run is written in
    this repository, and its message is the most useful thing an operator can be
    shown - "No model profile is configured for this agent" beats any sentence
    composed here. (The one place that folds a foreign `__str__` into an
    `AppException` is `sandbox_workspace._reason`, deliberately and for a route's
    answer; it runs outside both `try` blocks that call this.) `BudgetExceeded`
    never reaches this function: it is caught above and its ceiling is the point
    of it.

    Anything else is a foreign `__str__` and only its *type* is safe to store,
    plus the status code when a provider answered one. That code is what keeps
    the failures a person can act on themselves actionable - 401 a credential,
    404 a model the profile names and the provider does not have, 429 a rate
    limit, 400 a request the model refused - where a bare class name would make
    all four `ModelHTTPError`. An `int` has never carried a URL.

    A group is unwrapped to its first leaf first, the same unwrapping
    `failure_summary` and `probe_error_message` do. MCP toolsets and delegated
    runs sit on anyio task groups, so their failures arrive as an
    `ExceptionGroup` whose own name diagnoses nothing at all - which would spend
    the status code above on the failures most likely to carry one.
    """
    cause: BaseException = exc
    while isinstance(cause, BaseExceptionGroup):
        cause = cause.exceptions[0]
    if isinstance(cause, AppException):
        return str(cause)
    diagnosis = type(cause).__name__
    if isinstance(cause, ModelHTTPError):
        diagnosis = f"{diagnosis}, HTTP {cause.status_code}"
    return (
        f"The run did not finish ({diagnosis}) - retry it, and check the agent's model "
        "profile if it keeps failing. The server log has the full error."
    )
