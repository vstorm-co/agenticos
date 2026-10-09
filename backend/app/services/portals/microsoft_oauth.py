"""Microsoft Entra's OAuth, for connecting an organization's Microsoft 365 account.

The same shape as `google_oauth` - build a consent URL, exchange a code, hand
back a token and what was granted - with three differences that are Entra's:

**The endpoints are the tenant's.** `login.microsoftonline.com/{tenant}/...`,
with the tenant taken from the organization's `entra_app` secret - the app
registration SharePoint sync already signs in as. One registration serves both:
its *application* permissions are what a sync reads with, its *delegated* ones
what a connected account consents to, and Entra keeps the two apart.

**The code is bound with PKCE**, as Entra's v2 endpoints recommend for every
client, confidential ones included. The verifier rides in the sealed pending
payload, exactly as the MCP discovery flow's does.

**A refresh sends no `resource`.** The shared MCP refresh always sends one
(RFC 8707), and Entra's v2 token endpoint can refuse a request carrying it next
to `scope`, which is how v2 says which API a token is for. So the grant renews
here, with the scopes it was consented for, rather than through `mcp_oauth`.

`offline_access` is what yields a refresh token, and is asked for at connect
time with `User.Read` and nothing more: a portal that reads mail or a calendar
asks for its own scope when it is added, so connecting an account does not
consent to everything any portal might one day read.

**`AADSTS65001` is a decision, not a failure.** A tenant that lets only
administrators consent to an app answers a member's consent with it; nothing the
member retries will change that. It is raised as
:class:`MicrosoftAdminConsentRequired` so the card can say who has to act, and
:func:`admin_consent_url` is the link that administrator follows.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from app.services.microsoft_graph import GRAPH_ORIGIN, LOGIN

logger = logging.getLogger(__name__)

PROVIDER = "microsoft"
_TIMEOUT = httpx.Timeout(10.0)
# Entra's code for "this app needs an administrator's consent in this tenant".
ADMIN_CONSENT_REQUIRED = 65001
# Scopes OpenID Connect defines rather than Graph; the admin-consent endpoint
# wants Graph's permissions by their full URI, and these have none.
_OIDC_SCOPES = frozenset({"offline_access", "openid", "profile", "email"})


class MicrosoftOAuthError(Exception):
    """A recoverable failure exchanging or renewing a Microsoft grant, shown to the user."""


class MicrosoftAdminConsentRequired(MicrosoftOAuthError):
    """The tenant lets only an administrator consent to this app (`AADSTS65001`)."""


@dataclass(frozen=True)
class MicrosoftToken:
    """What a completed exchange or refresh yields.

    `granted_scopes` is Entra's space-separated `scope` response: what the
    account consented to, which a later portal checks before it reads anything.
    """

    access_token: str
    refresh_token: str | None
    expires_in: int | None
    granted_scopes: list[str]


def authorize_endpoint(tenant_id: str) -> str:
    """The tenant's v2 authorization endpoint."""
    return f"{LOGIN}/{tenant_id}/oauth2/v2.0/authorize"


def token_endpoint(tenant_id: str) -> str:
    """The tenant's v2 token endpoint."""
    return f"{LOGIN}/{tenant_id}/oauth2/v2.0/token"


def authorization_url(
    *,
    tenant_id: str,
    client_id: str,
    redirect_uri: str,
    scopes: Sequence[str],
    state: str,
    code_challenge: str,
) -> str:
    """The consent URL the browser is sent to.

    `prompt=select_account` lets whoever connects choose which of their signed-in
    accounts to grant, rather than silently granting the one the browser
    remembers. Not `prompt=consent`: Entra shows consent when it is needed, and
    forcing it on a tenant where only administrators consent is a refusal for
    every member, every time.
    """
    params = httpx.QueryParams(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return f"{authorize_endpoint(tenant_id)}?{params}"


def admin_consent_url(
    *, tenant_id: str, client_id: str, scopes: Sequence[str], redirect_uri: str
) -> str:
    """The link an Entra administrator follows to consent for the whole tenant.

    Asks for the delegated Graph permissions a connect asks for and nothing else
    - not `/.default`, which would consent to every permission the registration
    lists, application permissions for SharePoint sync included.
    """
    graph_scopes = [f"{GRAPH_ORIGIN}{scope}" for scope in scopes if scope not in _OIDC_SCOPES]
    params = httpx.QueryParams(
        {"client_id": client_id, "scope": " ".join(graph_scopes), "redirect_uri": redirect_uri}
    )
    return f"{LOGIN}/{tenant_id}/v2.0/adminconsent?{params}"


async def exchange_code(
    *,
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    scopes: Sequence[str],
) -> MicrosoftToken:
    """Trade the authorization code for tokens.

    Raises:
        MicrosoftAdminConsentRequired: The tenant requires an administrator's consent.
        MicrosoftOAuthError: Entra is unreachable, refused, or answered without a token.
    """
    return await _token_request(
        token_endpoint,
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
        },
    )


async def refresh_tokens(
    *,
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    scopes: Sequence[str],
) -> MicrosoftToken:
    """Renew an access token, without `resource` (see the module docstring).

    Entra rotates the refresh token on every use, so the answer's replaces the
    stored one; the caller holds the grant's row lock while it does.

    Raises:
        MicrosoftAdminConsentRequired: An administrator withdrew the tenant's consent.
        MicrosoftOAuthError: Entra is unreachable, refused, or answered without a token.
    """
    return await _token_request(
        token_endpoint,
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "scope": " ".join(scopes),
        },
    )


async def _token_request(url: str, form: dict[str, str]) -> MicrosoftToken:
    """POST to the token endpoint and read the answer.

    Entra's own text is neither returned nor logged: its `error_description`
    carries trace and correlation ids and, for some errors, the client id. What
    is logged is the error code and Entra's numeric `error_codes`, a fixed
    vocabulary an operator can look up.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, data=form, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        logger.warning("microsoft_oauth_unreachable", extra={"error": exc.__class__.__name__})
        raise MicrosoftOAuthError(
            "Microsoft could not be reached to complete the connection"
        ) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        logger.warning("microsoft_oauth_unreadable", extra={"status": response.status_code})
        raise MicrosoftOAuthError("Microsoft answered with something unreadable")
    if response.status_code >= 400:
        codes = payload.get("error_codes")
        codes = [code for code in codes if isinstance(code, int)] if isinstance(codes, list) else []
        error = payload.get("error")
        logger.warning(
            "microsoft_oauth_refused",
            extra={
                "status": response.status_code,
                "error": error if isinstance(error, str) else None,
                "error_codes": codes,
            },
        )
        if ADMIN_CONSENT_REQUIRED in codes:
            raise MicrosoftAdminConsentRequired(
                "Your administrator has to approve this app before the account can be connected"
            )
        raise MicrosoftOAuthError("Microsoft refused the connection request")
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
