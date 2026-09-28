"""Route-adjacent pieces of the directory sign-ins: the Negotiate exchange and the handoff.

Kerberos sign-in is a browser navigation, not an API call. The browser asks for
the sign-in URL, is answered `401 WWW-Authenticate: Negotiate`, and - on a
domain-joined machine whose policy trusts this host - asks again with a ticket.
Everything a browser without a ticket would render is the body of that first
401, so the body sends it straight back to the sign-in page with a sentence.

A completed sign-in ends the way an OIDC one does: a single-use code in the
redirect, which the frontend redeems server to server (`/oauth/exchange`), and
never a token in a URL.
"""

from __future__ import annotations

import base64
import binascii
import html
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.db.models.user import User
from app.services.oauth_exchange import OAuthExchangeService
from app.services.session import SessionService

_NEGOTIATE = "negotiate"

#: What a browser that cannot answer the challenge is sent back with.
NO_TICKET = "Windows sign-in is not available on this device. Sign in with your password instead."


def negotiate_token(authorization: str | None) -> bytes | None:
    """The SPNEGO token in an `Authorization: Negotiate <base64>` header, if there is one.

    Anything else - no header, a `Bearer`, a `Basic`, base64 that does not
    decode - is "no ticket", and the caller answers with the challenge.
    """
    if not authorization:
        return None
    scheme, _, credentials = authorization.partition(" ")
    if scheme.casefold() != _NEGOTIATE or not credentials.strip():
        return None
    try:
        return base64.b64decode(credentials.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None


def login_error_redirect(message: str) -> RedirectResponse:
    """Back to the sign-in page, carrying one sentence for the visitor."""
    frontend = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(url=f"{frontend}/login?{urlencode({'error': message})}")


def negotiate_challenge() -> HTMLResponse:
    """The `401 Negotiate` a browser answers with a ticket - or renders, when it has none.

    The rendered case is every browser outside the domain, and every one inside
    it whose policy does not list this host. A refresh to the sign-in page with
    the reason is what they see; a browser that does answer never renders it.
    """
    frontend = settings.FRONTEND_URL.rstrip("/")
    target = html.escape(f"{frontend}/login?{urlencode({'error': NO_TICKET})}", quote=True)
    body = (
        "<!doctype html><html><head>"
        f'<meta http-equiv="refresh" content="0;url={target}">'
        f'</head><body><a href="{target}">{html.escape(NO_TICKET)}</a></body></html>'
    )
    return HTMLResponse(
        content=body,
        status_code=401,
        headers={"WWW-Authenticate": "Negotiate", "Cache-Control": "no-store"},
    )


async def issue_sign_in_code(
    request: Request,
    user: User,
    *,
    exchange_service: OAuthExchangeService,
    session_service: SessionService,
) -> str:
    """Open a session for `user` and return the single-use code the frontend redeems.

    The session id is chosen before the code is issued, and the row written
    after, so a failure handing out the code leaves no phantom session behind -
    the order the OIDC callback uses for the same reason.
    """
    refresh_token = create_refresh_token(
        subject=str(user.id), credential_version=user.credential_version
    )
    session_id: UUID = uuid4()
    access_token = create_access_token(subject=str(user.id), sid=str(session_id))
    code = await exchange_service.issue(access_token=access_token, refresh_token=refresh_token)
    await session_service.create_session(
        user_id=user.id,
        refresh_token=refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
        session_id=session_id,
    )
    return code


def return_url(code: str, *, client: str | None, desktop_nonce: str | None) -> str:
    """Where the browser goes with the code: the console, or the desktop shell's deep link.

    `client` comes from the sign-in URL the shell opened, and the scheme is the
    deployment's setting - never the caller's - so this is not an open redirect.
    """
    if client == "desktop":
        params = urlencode({"code": code, "desktop_nonce": desktop_nonce or ""})
        return f"{settings.DESKTOP_DEEP_LINK_SCHEME}://auth/callback?{params}"
    return f"{settings.FRONTEND_URL.rstrip('/')}/auth/callback?{urlencode({'code': code})}"
