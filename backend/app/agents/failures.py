"""The one sentence a stored failure may hold, for exceptions it may not.

`run_failure_summary` began life in `app.services.agent_runner` (#676), which put
it out of the capability layer's reach - and a delegated run's row is composed
there, from the handle the subagents library settles. It lives here so both
layers write the same sentence for the same failure (#699).
"""

from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelHTTPError,
    ModelRequestTimeout,
    UsageLimitExceeded,
)

from app.core.exceptions import AppException

#: The turn that ended with the model producing nothing at all - no text, no
#: thinking, no tool call - raised by `RunFrames.drive` when a stream closes
#: with zero model events. Kept as a module constant so the guard and this
#: sentence cannot drift apart by one word.
NO_OUTPUT_MESSAGE = "The model run ended without producing any output"


def first_leaf(exc: BaseException) -> BaseException:
    """The first leaf of an exception group, or the exception itself.

    MCP toolsets and delegated runs sit on anyio task groups, so their
    failures arrive as an `ExceptionGroup` whose own name diagnoses nothing
    at all. A timeout that exhausted the fallback chain arrives the same
    way, as a `FallbackExceptionGroup` - unwrapping it is what lets a caller
    tell a timed-out run from a failed one.
    """
    cause: BaseException = exc
    while isinstance(cause, BaseExceptionGroup):
        cause = cause.exceptions[0]
    return cause


CONTENT_FILTER_SUMMARY = (
    "The model provider blocked this response with its content filter. "
    "The run stopped without a final answer."
)


def stored_failure_summary(error: str | None) -> str | None:
    """Recognize controlled provider refusals without publishing arbitrary historical errors.

    Older runs stored this provider refusal under its exception class. Other
    stored messages may predate redaction; shared transcripts get a generic
    failure state rather than copying an unknown error into another audience.
    """
    if error == CONTENT_FILTER_SUMMARY or (
        error is not None and error.startswith("The run did not finish (ContentFilterError) -")
    ):
        return CONTENT_FILTER_SUMMARY
    return None


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
    answer; it runs in a route service, outside every run a caller settles.)
    `BudgetExceeded` must not reach this function - each caller catches or
    filters it first, because its ceiling sentence is the point of it.

    Anything else is a foreign `__str__` and only its *type* is safe to store,
    plus the status code when a provider answered one. That code is what keeps
    the failures a person can act on themselves actionable - 401 a credential,
    404 a model the profile names and the provider does not have, 429 a rate
    limit, 400 a request the model refused - where a bare class name would make
    all four `ModelHTTPError`. An `int` has never carried a URL. A 402 has a
    sentence of its own, because the generic advice to retry is wrong for it.

    A group is unwrapped to its first leaf first, the same unwrapping
    `failure_summary` and `probe_error_message` do. MCP toolsets and delegated
    runs sit on anyio task groups, so their failures arrive as an
    `ExceptionGroup` whose own name diagnoses nothing at all - which would spend
    the status code above on the failures most likely to carry one.
    """
    cause = first_leaf(exc)
    if isinstance(cause, AppException):
        return str(cause)
    if isinstance(cause, ModelRequestTimeout):
        # A deadline, not a refusal: the model never answered, or never
        # started answering, within the time the run allowed it. The
        # sentence names which deadline and how long it was, because that
        # is what somebody has to change - and it is a distinct outcome
        # from a failed run, recorded as `timed_out` by the runner.
        if cause.setting == "first_event_timeout":
            return (
                f"The model did not answer within {cause.timeout:g} seconds "
                "without producing any output (ModelRequestTimeout, "
                "first_event_timeout). Try again; if it keeps happening, "
                "raise the first-event timeout in the agent's model settings "
                "or model profile."
            )
        return (
            f"The model did not finish within {cause.timeout:g} seconds "
            "(ModelRequestTimeout, request_timeout). Try again; if it keeps "
            "happening, raise the request timeout in the agent's model "
            "settings or model profile."
        )
    if isinstance(cause, RuntimeError) and str(cause) == NO_OUTPUT_MESSAGE:
        # The stream closed with zero model events: no text, no thinking,
        # no tool call. Nothing was refused and nothing was answered, so
        # neither the generic failure sentence nor a timeout sentence fits.
        return (
            "The model run ended without producing any output - no text, no "
            "thinking, no tool call. Try again; if it keeps happening, "
            "check the agent's model profile."
        )
    if isinstance(cause, ContentFilterError):
        return CONTENT_FILTER_SUMMARY
    diagnosis = type(cause).__name__
    if isinstance(cause, UsageLimitExceeded):
        # Not a fault to retry: the same task stops at the same limit again.
        return (
            "The run stopped at its step limit (UsageLimitExceeded). Raise `max_steps` "
            "in the agent's spec, or split the task into smaller requests."
        )
    if isinstance(cause, ModelHTTPError):
        if cause.status_code == 402:
            # "Retry it" is the wrong advice here: the account behind the model
            # profile cannot pay for the request, and a retry of the same
            # request is refused the same way until somebody adds credit.
            return (
                "The model provider refused the request for want of credit (HTTP 402). "
                "Add credit to the provider account behind the agent's model profile, or "
                "raise that API key's spending limit - a gateway such as OpenRouter caps "
                "each key on its own. A new conversation also carries less history."
            )
        diagnosis = f"{diagnosis}, HTTP {cause.status_code}"
    return (
        f"The run did not finish ({diagnosis}) - retry it, and check the agent's model "
        "profile if it keeps failing. The server log has the full error."
    )
