"""Microsoft's OAuth, for the trigger portal that reads an Outlook mailbox.

The same shape as `google_oauth`: build a consent URL, exchange a code, hand back
a token and the scopes that were actually granted. The client is the
organization's own app registration, a `microsoft_oauth_app` secret in the vault,
for the reason Google's is - every secret at rest goes through `app/core/vault.py`.

**The endpoints carry the tenant.** A single-tenant app registration - the usual
one a company makes for itself - only signs in through its own directory, so the
authorize and token URLs are built from the tenant the secret names rather than
fixed like Google's.

**Delegated, not application, permissions.** `Mail.Read` reads the mailbox of
whoever consents and `Mail.Read.Shared` the shared mailboxes they can already open;
neither needs an administrator, and neither reaches a mailbox the person could not
read themselves. `offline_access` is what yields a refresh token - without it the
grant lasts an hour.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

PROVIDER = "microsoft"
_LOGIN = "https://login.microsoftonline.com"
_TIMEOUT = httpx.Timeout(10.0)


class MicrosoftOAuthError(Exception):
    """A recoverable failure exchanging a Microsoft authorization code, shown to the user."""


@dataclass(frozen=True)
class MicrosoftToken:
    """What a completed exchange yields; `granted_scopes` is Microsoft's own `scope`."""

    access_token: str
    refresh_token: str | None
    expires_in: int | None
    granted_scopes: list[str]


def authorize_endpoint_for(tenant_id: str) -> str:
    return f"{_LOGIN}/{quote(tenant_id, safe='')}/oauth2/v2.0/authorize"


def token_endpoint_for(tenant_id: str) -> str:
    return f"{_LOGIN}/{quote(tenant_id, safe='')}/oauth2/v2.0/token"


def authorization_url(
    *, tenant_id: str, client_id: str, redirect_uri: str, scopes: Sequence[str], state: str
) -> str:
    """The consent URL the browser is sent to.

    `select_account` because the person connecting is often signed in to Microsoft
    as somebody else - a personal account, another tenant - and a silent consent
    would connect whichever mailbox the browser happened to hold.
    """
    params = httpx.QueryParams(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": " ".join(scopes),
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"{authorize_endpoint_for(tenant_id)}?{params}"


async def exchange_code(
    *,
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    scopes: Sequence[str],
) -> MicrosoftToken:
    """Trade the authorization code for tokens at the tenant's `token_endpoint`.

    Raises:
        MicrosoftOAuthError: The endpoint is unreachable, answered non-2xx, or
            answered without an access token. Microsoft's own text is logged as a
            status and not returned, for the reason Google's is not: an error body
            can echo the request, and the request carries the client secret.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                token_endpoint,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "scope": " ".join(scopes),
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        logger.warning("microsoft_oauth_unreachable", extra={"error": exc.__class__.__name__})
        raise MicrosoftOAuthError(
            "Microsoft could not be reached to complete the connection"
        ) from exc
    if response.status_code >= 400:
        logger.warning("microsoft_oauth_refused", extra={"status": response.status_code})
        raise MicrosoftOAuthError("Microsoft refused the connection request")
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("microsoft_oauth_unreadable")
        raise MicrosoftOAuthError("Microsoft answered with something unreadable") from exc
    if not isinstance(payload, dict):
        logger.warning("microsoft_oauth_unreadable")
        raise MicrosoftOAuthError("Microsoft answered with something unreadable")
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        logger.warning("microsoft_oauth_no_token", extra={"keys": sorted(payload)})
        raise MicrosoftOAuthError("Microsoft answered without an access token")
    refresh = payload.get("refresh_token")
    expires = payload.get("expires_in")
    return MicrosoftToken(
        access_token=token,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_in=expires if isinstance(expires, int) else None,
        granted_scopes=str(payload.get("scope") or "").split(),
    )
