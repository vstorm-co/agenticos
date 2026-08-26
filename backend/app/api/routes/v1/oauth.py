"""OAuth2 authentication routes."""

import logging
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.api.deps import OAuthExchangeSvc, UserSvc
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
async def google_login(request: Request, invitation: str | None = None):
    """Redirect to Google OAuth2 login page.

    `invitation` carries a shareable link's token through the round trip. Without
    it, an `invite_only` deployment refused the Google button for exactly the
    invitations that need it - a link constraining neither an address nor a domain
    is invisible to the address-based fallback, so the same person could register
    with a password and not with the provider offered beside it.
    """
    if invitation:
        request.session[_INVITATION_KEY] = invitation
    else:
        request.session.pop(_INVITATION_KEY, None)
    return await oauth.google.authorize_redirect(request, settings.GOOGLE_REDIRECT_URI)


@router.get("/google/callback", response_model=None)
async def google_callback(
    request: Request, user_service: UserSvc, exchange_service: OAuthExchangeSvc
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

        access_token = create_access_token(subject=str(user.id))
        refresh_token = create_refresh_token(subject=str(user.id))

        # A single-use code, not the tokens: a token in the redirect URL reaches
        # the address bar, the server access log, and the `Referer` of the next
        # same-origin request, and the refresh token is good for a week (#14).
        code = await exchange_service.issue(access_token=access_token, refresh_token=refresh_token)
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
