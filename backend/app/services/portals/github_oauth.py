"""GitHub's OAuth App authorization-code flow, with fixed endpoints and no discovery.

`app/agents/mcp_oauth` drives the *discovery* variant: it probes a server, resolves
an authorization server from RFC 9728 / 8414 metadata, and registers a client with
RFC 7591 dynamic registration. GitHub supports none of that against
`api.githubcopilot.com/mcp/`, so this module drives the classic OAuth App flow
instead: two fixed endpoints, and a `client_id`/`client_secret` an organization
registered by hand and stored in the vault (`github_oauth_app`).

Only the two provider-facing steps live here - build the consent URL, and exchange
the returned code for a token. Staging the pending flow and persisting the result are
the connection service's job, exactly as they are for the discovery flow.

GitHub's quirks, all handled here so nothing downstream has to know them:

- The token endpoint answers form-encoded unless asked for JSON, so the exchange
  sends `Accept: application/json`.
- The JSON response's `scope` is a comma-separated string, parsed into the
  granted-scope list the trigger-portal webhook path reads.
- A classic OAuth App token has no refresh token and no expiry; both are simply
  absent, and are stored as such rather than crashing the consumers that read them.
- A bad or expired code is answered with `200` and an `{"error": ...}` body, not a
  4xx, so success is the presence of an access token rather than the status code.

The host is fixed `github.com`, so there is no SSRF surface and no discovery hop to
validate. The token POST does not follow redirects.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# The discriminator stored on a pending `McpOAuthPayload` so the shared OAuth
# callback exchanges the code through this module rather than the discovery flow.
PROVIDER = "github"

AUTHORIZE_ENDPOINT = "https://github.com/login/oauth/authorize"
TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"
_TIMEOUT = httpx.Timeout(10.0)


class GithubOAuthError(Exception):
    """A recoverable failure exchanging a GitHub authorization code (shown to the user)."""


@dataclass(frozen=True)
class GithubToken:
    """What a completed exchange yields.

    `granted_scopes` is GitHub's comma-separated `scope` string parsed into a list -
    what the account actually consented to, which the webhook path checks against
    before it tries to register a hook. There is no refresh token or expiry because a
    classic OAuth App token has neither.
    """

    access_token: str
    granted_scopes: list[str]


def authorization_url(
    *, client_id: str, redirect_uri: str, scopes: Sequence[str], state: str
) -> str:
    """Build the consent URL the browser is redirected to.

    `allow_signup=false` keeps the consent screen from offering to create a new
    GitHub account mid-flow - the account connecting a repository already has one.
    """
    params = httpx.QueryParams(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "allow_signup": "false",
        }
    )
    return f"{AUTHORIZE_ENDPOINT}?{params}"


async def exchange_code(
    *, client_id: str, client_secret: str, code: str, redirect_uri: str
) -> GithubToken:
    """Exchange an authorization code for an access token.

    Raises:
        GithubOAuthError: The endpoint could not be reached, answered non-200,
            answered with an error body, or returned no access token. A transport
            failure - a timeout, a refused connection, a dropped response - is
            translated too, because the shared OAuth callback turns this error
            into its recoverable `ok=false` result and anything else into a 500;
            an ordinary GitHub outage is the user's to retry, not a server error.
            The message is a fixed string - the response body carries the token on
            success and an error description on failure, and neither belongs in a
            log line or a browser toast.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            response = await client.post(
                TOKEN_ENDPOINT,
                headers={"Accept": "application/json"},
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
    except httpx.HTTPError as exc:
        logger.warning("github_token_exchange_unreachable", extra={"error": type(exc).__name__})
        raise GithubOAuthError(
            "GitHub could not be reached - please try connecting again."
        ) from exc
    if response.status_code != 200:
        logger.warning("github_token_exchange_failed", extra={"status": response.status_code})
        raise GithubOAuthError("GitHub rejected the authorization - please try connecting again.")
    try:
        body = response.json()
    except ValueError as exc:
        # A 200 whose body is not JSON - an intermediary's error page, a truncated
        # response. The shared callback only recovers GithubOAuthError into its
        # ok=false result, so this must arrive as that error, not a 500.
        logger.warning("github_token_exchange_unreadable")
        raise GithubOAuthError(
            "GitHub answered with something unreadable - please try connecting again."
        ) from exc
    if not isinstance(body, dict):
        logger.warning("github_token_exchange_unreadable")
        raise GithubOAuthError(
            "GitHub answered with something unreadable - please try connecting again."
        )
    if "error" in body:
        # A 200 with an error payload is how GitHub reports a bad or expired code.
        logger.warning("github_token_exchange_error", extra={"error": body.get("error")})
        raise GithubOAuthError("GitHub could not complete the authorization - please try again.")
    access_token = body.get("access_token")
    if not access_token:
        logger.warning("github_token_exchange_no_token")
        raise GithubOAuthError("GitHub returned no access token - please try connecting again.")
    scope = body.get("scope") or ""
    granted_scopes = [item for item in scope.split(",") if item]
    return GithubToken(access_token=access_token, granted_scopes=granted_scopes)
