"""User management routes."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, Query, Request, UploadFile, status

from app.api.deps import (
    CurrentAppAdmin,
    CurrentSessionId,
    CurrentUser,
    DBSession,
    DeploymentSettingsSvc,
    UserSvc,
)
from app.api.routes.v1._stored_bytes import stored_image_response
from app.api.routes.v1.admin_users import delete_user as admin_delete_user
from app.api.routes.v1.admin_users import update_user as admin_update_user
from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.schemas.user import UserRead, UserUpdate
from app.services.email.service import get_email_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/me", response_model=UserRead)
async def read_current_user(
    current_user: CurrentUser,
) -> Any:
    """Get current user profile."""
    return current_user


@router.patch("/me", response_model=UserRead)
async def update_current_user(
    user_in: UserUpdate,
    current_user: CurrentUser,
    user_service: UserSvc,
    current_session_id: CurrentSessionId,
    branding: DeploymentSettingsSvc,
) -> Any:
    """Update current user profile.

    No privilege can be granted from here. `UserUpdate` carries no role and no
    `is_app_admin`, so the guard this used to need - stripping a role a
    non-admin had put in the body - has nothing left to strip. Granting the one
    global privilege is a CLI act (`agenticos cmd create-app-admin`), which
    keeps it off the surface a user can PATCH.

    It can still take one away from its owner, though: `is_active` is on this
    schema and this route reaches the same column the admin route does, so
    `update_current` refuses an app admin suspending themselves here - otherwise
    it is the way around #941's guard.

    An `email` is *staged* rather than written, and this route mails the proof it
    waits for: a link to the new address, and a notice to the old one saying the
    change was asked for. The account keeps using its current address until that
    link comes back (#1772), which is why the answer still carries it -
    `pending_email` beside it is what the form reads to say so.
    """
    updated, token = await user_service.update_current(
        current_user, user_in, current_session_id=current_session_id
    )
    if token is not None and updated.pending_email is not None:
        app_name = await branding.effective_app_name()
        name = updated.full_name or updated.email
        # Best-effort, like every other send on this surface: the staging is
        # committed either way, and a provider outage must not roll back the
        # rest of the patch. The address simply stays unconfirmed, which is the
        # safe end of the two.
        try:
            confirm_url = f"{settings.FRONTEND_URL.rstrip('/')}/auth/email-change?token={token}"
            await get_email_service().send_email_change_verification(
                to=updated.pending_email, name=name, confirm_url=confirm_url, app_name=app_name
            )
            await get_email_service().send_email_change_notice(
                to=updated.email, name=name, new_email=updated.pending_email, app_name=app_name
            )
        except Exception:
            logger.exception("email_change_mail_failed", extra={"user_id": str(updated.id)})
    return updated


@router.post("/me/avatar", response_model=UserRead)
async def upload_avatar(
    user_service: UserSvc,
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> Any:
    """Upload or replace avatar image for the current user."""
    data = await file.read()
    try:
        user = await user_service.update_avatar(current_user.id, data, file.content_type or "")
    except ValueError as e:
        raise BadRequestError(message=str(e)) from None
    return user


@router.get("/avatar/{user_id}", response_model=None)
async def get_avatar(user_id: UUID, user_service: UserSvc) -> Any:
    """Get user avatar image."""
    user = await user_service.get_by_id(user_id)
    if not user.avatar_url:
        raise NotFoundError(message="No avatar set")
    # Pinned to the file's actual image type, and refused if it is not an image at
    # all: the avatar is served from the app's own origin, and the upload kept
    # whatever suffix the caller's filename had (#702). Hardcoding image/jpeg here
    # named a lie for a stored png and, worse, said nothing about a stored .html.
    response = await stored_image_response(
        user.avatar_url, headers={"X-Content-Type-Options": "nosniff"}
    )
    if response is None:
        raise NotFoundError(message="Avatar file not found")
    return response


@router.get("/{user_id}", response_model=UserRead)
async def read_user(
    user_id: UUID,
    user_service: UserSvc,
    _: CurrentAppAdmin,
) -> Any:
    """Get user by ID (admin only)."""
    return await user_service.get_by_id(user_id)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user_by_id(
    user_id: UUID,
    user_in: UserUpdate,
    request: Request,
    admin: CurrentAppAdmin,
    db: DBSession,
    user_service: UserSvc,
) -> Any:
    """Update user by ID (admin only).

    Delegates to `admin_users.update_user` rather than repeating its audit
    and notification write here - the two routers reach the same action from
    two paths, and a second copy of "record it, then notify" is a second copy
    that silently stopped being audited when only one of them was kept
    current (#1598).
    """
    return await admin_update_user(user_id, user_in, request, admin, db, user_service)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_user_by_id(
    user_id: UUID,
    request: Request,
    admin: CurrentAppAdmin,
    db: DBSession,
    user_service: UserSvc,
    reason: str | None = Query(
        default=None,
        max_length=500,
        description="Why this account was deleted. Recorded in the audit trail.",
    ),
) -> None:
    """Delete user by ID (admin only). Delegates to `admin_users.delete_user`,
    for the same reason `update_user_by_id` above does."""
    await admin_delete_user(user_id, request, admin, db, user_service, reason=reason)
