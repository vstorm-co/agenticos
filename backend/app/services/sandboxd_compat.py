"""Whether a `sandboxd` serves the endpoints this platform's client calls.

The service and its client ship from one repository (`pydantic-ai-backend`) and
move together: a client that calls `POST /sessions/{id}/run` against a service
that only knows `/exec` gets FastAPI's own 404, and the client reads every 404 on
a session route as "the session is gone" (#2484). The session is alive; the two
halves are from different releases. Told that the workspace is gone, the model
gives up and the conversation's session is forgotten - for a problem only the
operator can fix, by running the image that matches.

So a 404 is looked at once more before it is believed. The service's own 404s
always name what is missing (`No such session: ...`); a route the service does
not have answers with FastAPI's bare `{"detail":"Not Found"}`. Only that body
costs one more request - to the service's unauthenticated index, which lists the
routes it serves - and only a route the client needs and the index lacks is
reported as a version mismatch. Anything less certain stays the error it was.
"""

import logging
from importlib.metadata import version

import httpx
from pydantic import BaseModel
from pydantic_ai.workspaces import WorkspaceUnavailableError

from app.core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

SANDBOXD_IMAGE = "ghcr.io/vstorm-co/sandboxd"
"""The published image of the service."""

SANDBOXD_VERSION = version("pydantic-ai-backend")
"""The service release this platform's client speaks to: the same version.

The compose files pin `SANDBOXD_IMAGE` at exactly this tag, and a test holds them
to it, so a bump of `pydantic-ai-backend` in `uv.lock` moves the image with it.
"""

REQUIRED_ENDPOINTS = (
    "/policy",
    "/sessions",
    "/sessions/{session_id}",
    "/sessions/{session_id}/run",
    "/sessions/{session_id}/runs/{run_id}/stop",
)
"""Every route the workspace client calls whatever the service's policy says.

The native file routes are left out: the client uses them only when the policy
offers them, and falls back to `/run` when it does not.
"""

_ROUTE_NOT_FOUND = '{"detail":"Not Found"}'
"""FastAPI's body for a path no route matches. The service's own 404s say more."""

_INDEX_TIMEOUT_SECONDS = 5.0


class _Index(BaseModel):
    """The part of the service's index at `/` read here: the routes it serves."""

    endpoints: list[str]


class SandboxdVersionMismatchError(ConfigurationError, WorkspaceUnavailableError):
    """The service does not serve a route the client needs: the versions differ.

    A `WorkspaceUnavailableError`, so the tool call fails as it would for a lost
    session - no command can succeed - and the model is told why. Its message
    names neither the service's address nor anything else from the connection:
    a run's error and a tool result are read by members and the model, who may
    not see the connection (#342).
    """

    message = "This sandbox service does not match this platform's version"
    code = "SANDBOXD_VERSION_MISMATCH"


def mismatch_message(missing: list[str]) -> str:
    """What to tell an operator whose service lacks `missing`, and what to do about it."""
    return (
        f"The sandbox service does not serve {', '.join(missing)} - its version does not "
        f"match this platform (expected {SANDBOXD_VERSION}). Run "
        f"{SANDBOXD_IMAGE}:{SANDBOXD_VERSION} and redeploy it"
    )


async def missing_endpoints(client: httpx.AsyncClient, base_url: str) -> list[str]:
    """The routes in `REQUIRED_ENDPOINTS` that the service at `base_url` does not serve.

    Read from the service's index at `/`, which is unauthenticated and lists its
    routes. Every published sandboxd has one, so a `/` that answers with an error
    is something in front of the service, and says nothing about its version.

    Raises:
        httpx.HTTPError: The service could not be reached or `/` answered with an
            error.
        ValueError: It answered with something that is not a sandboxd index
            (`pydantic.ValidationError` is one).
    """
    base = base_url.rstrip("/")
    response = await client.get(f"{base}/", timeout=_INDEX_TIMEOUT_SECONDS)
    response.raise_for_status()
    served = _Index.model_validate(response.json()).endpoints
    return [path for path in REQUIRED_ENDPOINTS if path not in served]


async def explain_unavailable(
    error: WorkspaceUnavailableError, *, base_url: str, client: httpx.AsyncClient
) -> SandboxdVersionMismatchError | None:
    """The version mismatch behind a "session is gone", or `None` if it really is gone.

    Asks the service's index only when the error carries FastAPI's bare 404, and
    keeps the original error whenever the index cannot settle it - unreachable,
    not an index, or listing every route the client needs.
    """
    if not str(error).endswith(_ROUTE_NOT_FOUND):
        return None
    try:
        missing = await missing_endpoints(client, base_url)
    except httpx.HTTPError, ValueError:
        return None
    if not missing:
        return None
    # The address goes to the operator's log only, not into the error.
    logger.warning(
        "sandboxd_version_mismatch",
        extra={"base_url": base_url, "missing": missing, "expected": SANDBOXD_VERSION},
    )
    return SandboxdVersionMismatchError(
        message=mismatch_message(missing),
        details={"missing": missing, "expected": SANDBOXD_VERSION},
    )
