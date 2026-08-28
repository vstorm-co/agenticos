"""Authentication routes."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import (
    CurrentUser,
    DeploymentSettingsSvc,
    SessionSvc,
    UserSvc,
    enforce_auth_limit,
)
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
)
from app.schemas.password_reset import (
    MagicLinkRequest,
    MagicLinkVerifyRequest,
    PasswordResetConfirm,
    PasswordResetConfirmResponse,
    PasswordResetRequest,
    PasswordResetResponse,
)
from app.schemas.token import MagicLinkToken, RefreshTokenRequest, Token
from app.schemas.user import UserCreate, UserRead
from app.services.email.service import get_email_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_service: UserSvc,
    session_service: SessionSvc,
) -> Any:
    """OAuth2 password login, returns access and refresh tokens."""
    await enforce_auth_limit(request, surface="auth_login", identifier=form_data.username)
    user = await user_service.authenticate(form_data.username, form_data.password)
    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))

    # Track this login as a server-side session (enables remote logout).
    await session_service.create_session(
        user_id=user.id,
        refresh_token=refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    user_in: UserCreate,
    user_service: UserSvc,
) -> Any:
    """Register a new user."""
    await enforce_auth_limit(request, surface="auth_register", identifier=user_in.email)
    return await user_service.register(user_in)


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,
    body: RefreshTokenRequest,
    user_service: UserSvc,
    session_service: SessionSvc,
) -> Any:
    """Exchange a refresh token for a new access token."""
    await enforce_auth_limit(request, surface="auth_refresh")

    session = await session_service.validate_refresh_token(body.refresh_token)
    if not session:
        raise AuthenticationError(message="Invalid or expired refresh token")

    user = await user_service.get_by_id(session.user_id)
    if not user.is_active:
        raise AuthenticationError(message="User account is disabled")

    access_token = create_access_token(subject=str(user.id))
    new_refresh_token = create_refresh_token(subject=str(user.id))

    await session_service.logout_by_refresh_token(body.refresh_token)
    await session_service.create_session(
        user_id=user.id,
        refresh_token=new_refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return Token(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout(
    request: Request,
    body: RefreshTokenRequest,
    session_service: SessionSvc,
) -> None:
    """Logout and invalidate the current session.

    Invalidates the refresh token, preventing further token refresh.
    """
    await enforce_auth_limit(request, surface="auth_logout")
    await session_service.logout_by_refresh_token(body.refresh_token)


@router.get("/me", response_model=UserRead)
async def get_current_user_info(current_user: CurrentUser) -> Any:
    """Get current authenticated user information."""
    return current_user


@router.post("/password-reset/request", response_model=PasswordResetResponse)
async def request_password_reset(
    request: Request,
    body: PasswordResetRequest,
    user_service: UserSvc,
    branding: DeploymentSettingsSvc,
) -> Any:
    """Email a single-use reset link to the address.

    Always returns 200 with the same body - we don't disclose whether the
    email is in our system. The caller (email service) is best-effort.
    """
    await enforce_auth_limit(request, surface="auth_password_reset", identifier=body.email)
    issued = await user_service.issue_password_reset_token(body.email)
    if issued is not None:
        reset_user, token = issued
        try:
            reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
            await get_email_service().send_password_reset(
                to=body.email,
                name=reset_user.full_name or body.email,
                reset_url=reset_url,
                app_name=await branding.effective_app_name(),
            )
        except Exception:
            logger.exception("password_reset_email_failed", extra={"email": body.email})
    return PasswordResetResponse()


@router.post("/password-reset/confirm", response_model=PasswordResetConfirmResponse)
async def confirm_password_reset(
    request: Request,
    body: PasswordResetConfirm,
    user_service: UserSvc,
) -> Any:
    """Set a new password using a token from the reset email."""
    await enforce_auth_limit(request, surface="auth_password_reset_confirm")
    await user_service.confirm_password_reset(body.token, body.new_password)
    return PasswordResetConfirmResponse()


@router.post("/magic-link/request", response_model=PasswordResetResponse)
async def request_magic_link(
    request: Request,
    body: MagicLinkRequest,
    user_service: UserSvc,
    branding: DeploymentSettingsSvc,
) -> Any:
    """Email a single-use sign-in link.

    Symmetric response to request_password_reset to avoid email enumeration.
    """
    await enforce_auth_limit(request, surface="auth_magic_link", identifier=body.email)
    issued = await user_service.issue_magic_link_token(body.email, return_to=body.return_to)
    if issued is not None:
        link_user, token = issued
        try:
            login_url = f"{settings.FRONTEND_URL.rstrip('/')}/auth/magic-link?token={token}"
            await get_email_service().send_welcome(
                to=body.email,
                name=link_user.full_name or body.email,
                login_url=login_url,
                app_name=await branding.effective_app_name(),
            )
        except Exception:
            logger.exception("magic_link_email_failed", extra={"email": body.email})
    return PasswordResetResponse(message="Check your email for a sign-in link.")


@router.post("/magic-link/verify", response_model=MagicLinkToken)
async def verify_magic_link(
    request: Request,
    body: MagicLinkVerifyRequest,
    user_service: UserSvc,
    session_service: SessionSvc,
) -> Any:
    """Exchange a magic-link token for an access + refresh token pair.

    Answers with the return path the link was minted for, unapplied: the client
    navigates, and `postSignInDestination` there is the one place that decides
    whether a path is safe to honour - the same judgement for every door in.
    """
    await enforce_auth_limit(request, surface="auth_magic_link_verify")
    user, return_to = await user_service.consume_magic_link_token(body.token)
    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))
    await session_service.create_session(
        user_id=user.id,
        refresh_token=refresh_token,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return MagicLinkToken(
        access_token=access_token, refresh_token=refresh_token, return_to=return_to
    )
