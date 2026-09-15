"""Signing somebody in through an identity provider.

One pair of routes for every provider, because the flow is one flow: OpenID
Connect's authorization-code exchange, ending in a single-use code the frontend
swaps for the token pair. `google` and a deployment's own `oidc` differ in their
discovery document and in nothing this module does (#1419).
"""

import logging
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.api.deps import InvitationStagingSvc, OAuthExchangeSvc, SessionSvc, UserSvc
from app.api.routes.v1._oauth_claims import claims_for
from app.core.config import settings
from app.core.exceptions import AppException, AuthenticationError
from app.core.oauth import identity_key, redirect_uri_for, sign_in_client, verified_identity
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


@router.get("/{provider}/login", response_model=None)
async def provider_login(
    provider: str,
    request: Request,
    staging: InvitationStagingSvc,
    invitation_handle: str | None = None,
):
    """Send the browser to `provider` to sign in.

    `invitation_handle` names the invitation a signed-out invitee staged before the
    sign-in detour (#1414). It is peeked - not consumed - into the token the callback
    needs for admission, so the raw token never rides this query and the same handle
    still closes the acceptance afterwards. Without it an `invite_only` deployment
    refused the provider button for exactly the invitations that need it: a link
    constraining neither an address nor a domain is invisible to the address-based
    fallback, so the same person could register with a password and not with the
    provider offered beside it.
    """
    client = sign_in_client(provider)
    token = await staging.peek(invitation_handle) if invitation_handle else None
    if token:
        request.session[_INVITATION_KEY] = token
    else:
        request.session.pop(_INVITATION_KEY, None)
    return await client.authorize_redirect(request, redirect_uri_for(provider))


@router.get("/{provider}/callback", response_model=None)
async def provider_callback(
    provider: str,
    request: Request,
    user_service: UserSvc,
    exchange_service: OAuthExchangeSvc,
    session_service: SessionSvc,
):
    """Finish the round trip and hand the frontend a code for its tokens."""
    client = sign_in_client(provider)
    frontend = settings.FRONTEND_URL.rstrip("/")
    try:
        token = await client.authorize_access_token(request)
        identity = verified_identity(await claims_for(client, token))

        if identity is None:
            # One sentence for three refusals - no subject, no address, an
            # address the provider has not verified. Which one it was goes to
            # the log: a redirect a stranger can read is not the place to say
            # that an address exists at this provider but is unconfirmed.
            logger.warning("oauth_callback_claims_rejected", extra={"provider": provider})
            params = urlencode({"error": "That account cannot be used to sign in here."})
            return RedirectResponse(url=f"{frontend}/login?{params}")

        subject, email, full_name = identity

        # Taken off the session rather than read: an invitation is consumed by the
        # attempt it was started for, so a token left behind cannot admit a second,
        # unrelated sign-in from the same browser.
        user = await user_service.get_or_create_oauth_user(
            provider=provider,
            # Namespaced by issuer for the generic provider: an OIDC `sub` is
            # unique within its issuer and nowhere else, and this match happens
            # before the address is ever compared.
            provider_id=identity_key(provider, subject),
            email=email,
            full_name=full_name,
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

    except AppException as exc:
        # A refusal this repository wrote, and the sign-up policy is the one that
        # matters: an `invite_only` or domain-limited deployment must turn an OIDC
        # sign-in away exactly as it turns the registration form away, or closing
        # sign-up closes nothing. Its sentence was written for the person reading
        # it, so it is carried to the login page rather than flattened into
        # "Sign-in failed" beside every timeout and misconfiguration.
        logger.warning("oauth_callback_refused", extra={"provider": provider})
        params = urlencode({"error": exc.message})
        return RedirectResponse(url=f"{frontend}/login?{params}")
    except Exception:
        logger.exception("oauth_callback_failed", extra={"provider": provider})
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
