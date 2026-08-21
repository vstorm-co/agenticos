"""Google's OAuth, for a trigger portal that reads a mailbox.

Google publishes fixed endpoints and does not support the discovery-and-dynamic-
registration flow `mcp_oauth` runs, so this is the same shape as
`github_oauth`: build a consent URL, exchange a code, hand back a token and the
scopes that were actually granted.

**The client is the deployment's own**, `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
- the pair a self-hosted install already registers for Google sign-in - rather than
a per-organization OAuth App the way GitHub does it. Two reasons. Google's consent
screen for a `gmail.readonly` scope needs a verified project, which is an
application an operator makes once and no tenant of theirs can make at all; and
this is a self-hosted product, so "the deployment's Google project" is already the
unit an operator owns. GitHub asks per organization because its App *is* free to
register and because a repository webhook is registered under whoever owns the App.

`access_type=offline` with `prompt=consent` is what yields a refresh token: without
it Google returns one only on the very first consent for a client, so an
organization that had ever signed in with Google would get an access token that
expires in an hour and no way to renew it - a mailbox that works for an hour and
then silently stops.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

PROVIDER = "google"
AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_TIMEOUT = httpx.Timeout(10.0)


class GoogleOAuthError(Exception):
    """A recoverable failure exchanging a Google authorization code, shown to the user."""


@dataclass(frozen=True)
class GoogleToken:
    """What a completed exchange yields.

    `granted_scopes` is Google's space-separated `scope` response parsed into a
    list: consent is per scope and a person can withhold one, so what was asked
    for is not what was granted - and the poller has to know which it got before
    it reads a mailbox it may not have been given.
    """

    access_token: str
    refresh_token: str | None
    expires_in: int | None
    granted_scopes: list[str]


def authorization_url(
    *, client_id: str, redirect_uri: str, scopes: Sequence[str], state: str
) -> str:
    """The consent URL the browser is sent to.

    `include_granted_scopes` makes Google return a token covering everything this
    client already holds for the account as well as what is being asked for now,
    so adding a second scope later does not silently drop the first.
    """
    params = httpx.QueryParams(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
    )
    return f"{AUTHORIZE_ENDPOINT}?{params}"


async def exchange_code(
    *, client_id: str, client_secret: str, code: str, redirect_uri: str
) -> GoogleToken:
    """Trade the authorization code for tokens.

    Raises:
        GoogleOAuthError: The endpoint is unreachable, answered non-2xx, or
            answered without an access token. The provider's own text is logged
            and not returned: a token endpoint's error body has been known to echo
            the request, and the request carries the client secret.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                TOKEN_ENDPOINT,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        logger.warning("google_oauth_unreachable", extra={"error": exc.__class__.__name__})
        raise GoogleOAuthError("Google could not be reached to complete the connection") from exc
    if response.status_code >= 400:
        logger.warning("google_oauth_refused", extra={"status": response.status_code})
        raise GoogleOAuthError("Google refused the connection request")
    payload = response.json()
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        logger.warning("google_oauth_no_token", extra={"keys": sorted(payload)})
        raise GoogleOAuthError("Google answered without an access token")
    refresh = payload.get("refresh_token")
    expires = payload.get("expires_in")
    return GoogleToken(
        access_token=token,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_in=expires if isinstance(expires, int) else None,
        granted_scopes=str(payload.get("scope") or "").split(),
    )
