"""OAuth2 authentication routes."""

import logging
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.api.deps import InvitationStagingSvc, OAuthExchangeSvc, SessionSvc, UserSvc
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.oauth import oauth
from app.core.security import create_access_token, create_refresh_token
from app.schemas.token import OAuthExchangeRequest, Token

logger = logging.getLogger(__name__)

router = APIRouter()


#: Where an invitation token waits while the caller is away at the provider.
#:
#: The session cookie authlib already uses for its own CSRF `state`, because the
#: token has to survive a round trip this app does not control and must not travel
#: back through a query string somebody can hand to a third party. Holding the
#: token *is* the proof an invitation admits an address nothing else recognises, so
#: it is kept where only this browser can produce it.
_INVITATION_KEY = "oauth_invitation_token"


@router.get("/google/login", response_model=None)
async def google_login(
    request: Request,
    staging: InvitationStagingSvc,
    invitation_handle: str | None = None,
):
    """Redirect to Google OAuth2 login page.

    `invitation_handle` names the invitation a signed-out invitee staged before the
    sign-in detour (#1414). It is peeked - not consumed - into the token the callback
    needs for admission, so the raw token never rides this query and the same handle
    still closes the acceptance afterwards. Without it an `invite_only` deployment
    refused the Google button for exactly the invitations that need it: a link
    constraining neither an address nor a domain is invisible to the address-based
    fallback, so the same person could register with a password and not with the
    provider offered beside it.
    """
    token = await staging.peek(invitation_handle) if invitation_handle else None
    if token:
        request.session[_INVITATION_KEY] = token
    else:
        request.session.pop(_INVITATION_KEY, None)
    return await oauth.google.authorize_redirect(request, settings.GOOGLE_REDIRECT_URI)


@router.get("/google/callback", response_model=None)
async def google_callback(
    request: Request,
    user_service: UserSvc,
    exchange_service: OAuthExchangeSvc,
    session_service: SessionSvc,
):
    """Handle Google OAuth2 callback."""
    frontend = settings.FRONTEND_URL.rstrip("/")
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")

        if not user_info:
            params = urlencode({"error": "Failed to get user info from Google"})
            return RedirectResponse(url=f"{frontend}/login?{params}")

        # Taken off the session rather than read: an invitation is consumed by the
        # attempt it was started for, so a token left behind cannot admit a second,
        # unrelated sign-in from the same browser.
        user = await user_service.get_or_create_oauth_user(
            provider="google",
            provider_id=user_info.get("sub"),
            email=user_info.get("email"),
            full_name=user_info.get("name"),
            invitation_token=request.session.pop(_INVITATION_KEY, None),
        )

        refresh_token = create_refresh_token(subject=str(user.id))

        # An OAuth sign-in is an ordinary session, so the access token names its
        # session row in `sid` - otherwise signing out everywhere could not revoke
        # it, the way it could not for any login before #1501. The id is chosen up
        # front so the row can be written *after* the code is issued: a failure
        # handing out the code then leaves no phantom session behind.
        session_id = uuid4()
        access_token = create_access_token(subject=str(user.id), sid=str(session_id))

        # A single-use code, not the tokens: a token in the redirect URL reaches
        # the address bar, the server access log, and the `Referer` of the next
        # same-origin request, and the refresh token is good for a week (#14).
        code = await exchange_service.issue(access_token=access_token, refresh_token=refresh_token)
        await session_service.create_session(
            user_id=user.id,
            refresh_token=refresh_token,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
            session_id=session_id,
        )
        params = urlencode({"code": code})
        return RedirectResponse(url=f"{frontend}/auth/callback?{params}")

    except Exception:
        logger.exception("google_oauth_callback_failed")
        params = urlencode({"error": "Sign-in failed. Please try again."})
        return RedirectResponse(url=f"{frontend}/login?{params}")


@router.post("/exchange", response_model=Token)
async def exchange_code(body: OAuthExchangeRequest, exchange_service: OAuthExchangeSvc) -> Any:
    """Swap a single-use OAuth code for its token pair, server to server."""
    tokens = await exchange_service.redeem(body.code)
    if tokens is None:
        raise AuthenticationError(message="Invalid or expired exchange code")
    access_token, refresh_token = tokens
    return Token(access_token=access_token, refresh_token=refresh_token)
