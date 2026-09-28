"""Signing in with a directory account: an LDAP password, or a Kerberos ticket.

Both answer 404 on a deployment that configured neither, like an OIDC provider
nobody set up, so the sign-in methods a company runs are not enumerable from
outside (#1773).
"""

import base64
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.api.deps import (
    DirectorySignInSvc,
    InvitationStagingSvc,
    OAuthExchangeSvc,
    SessionSvc,
    enforce_auth_limit,
)
from app.api.routes.v1._directory_handoff import (
    issue_sign_in_code,
    login_error_redirect,
    negotiate_challenge,
    negotiate_token,
    return_url,
)
from app.core.exceptions import AppException
from app.core.security import create_access_token, create_refresh_token
from app.schemas.directory import DirectoryLogin
from app.schemas.token import Token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ldap/login", response_model=Token)
async def ldap_login(
    request: Request,
    body: DirectoryLogin,
    sign_in: DirectorySignInSvc,
    session_service: SessionSvc,
    staging: InvitationStagingSvc,
) -> Any:
    """Sign in with a directory account's username and password.

    The account is created on the first sign-in, under the deployment's sign-up
    policy, and the person's memberships are reconciled with the directory group
    mappings on every one. Rate-limited per address and per username, like the
    password login beside it.
    """
    await enforce_auth_limit(request, surface="auth_ldap_login", identifier=body.username)
    invitation_token = (
        await staging.peek(body.invitation_handle) if body.invitation_handle else None
    )
    user = await sign_in.sign_in_with_password(
        body.username, body.password, invitation_token=invitation_token
    )
    refresh_token = create_refresh_token(
        subject=str(user.id), credential_version=user.credential_version
    )
    session = await session_service.create_session(
        user_id=user.id,
        refresh_token=refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    access_token = create_access_token(subject=str(user.id), sid=str(session.id))
    return Token(access_token=access_token, refresh_token=refresh_token)


@router.get("/kerberos/login", response_model=None)
async def kerberos_login(
    request: Request,
    sign_in: DirectorySignInSvc,
    exchange_service: OAuthExchangeSvc,
    session_service: SessionSvc,
    staging: InvitationStagingSvc,
    invitation_handle: str | None = None,
    client: str | None = None,
    desktop_nonce: str | None = None,
) -> Any:
    """Sign in with the Kerberos ticket of a domain-joined browser (SPNEGO).

    Without a ticket the answer is the `401 Negotiate` challenge; with one, a
    redirect carrying a single-use code, exactly as an OIDC sign-in ends. The
    query parameters survive the challenge because the browser repeats the same
    URL, which is how an invitation and the desktop shell's return ride along.
    """
    sign_in.require_kerberos()
    token = negotiate_token(request.headers.get("Authorization"))
    if token is None:
        return negotiate_challenge()
    try:
        await enforce_auth_limit(request, surface="auth_kerberos_login")
        invitation_token = await staging.peek(invitation_handle) if invitation_handle else None
        user, response_token = await sign_in.sign_in_with_ticket(
            token, invitation_token=invitation_token
        )
        code = await issue_sign_in_code(
            request, user, exchange_service=exchange_service, session_service=session_service
        )
    except AppException as exc:
        # Our own refusals - a rejected ticket, the sign-up policy, an account
        # the directory cannot resolve - carry sentences written for the person
        # reading them, and this is a browser navigation, so they go to the
        # sign-in page rather than into a JSON body nobody sees.
        logger.warning("kerberos_sign_in_refused", extra={"code": exc.code})
        return login_error_redirect(exc.message)
    except Exception:
        logger.exception("kerberos_sign_in_failed")
        return login_error_redirect("Sign-in failed. Please try again.")
    response = RedirectResponse(url=return_url(code, client=client, desktop_nonce=desktop_nonce))
    if response_token:
        # Mutual authentication: the browser may check that it reached the
        # service its ticket was for.
        response.headers["WWW-Authenticate"] = (
            f"Negotiate {base64.b64encode(response_token).decode('ascii')}"
        )
    return response
