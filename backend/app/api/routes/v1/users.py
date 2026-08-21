"""User management routes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import (
    CurrentAppAdmin,
    CurrentUser,
    UserSvc,
)
from app.core.exceptions import BadRequestError, NotFoundError
from app.schemas.user import UserRead, UserUpdate

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
    """
    return await user_service.update_current(current_user, user_in)


@router.post("/me/avatar", response_model=UserRead)
async def upload_avatar(
    user_service: UserSvc,
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> Any:
    """Upload or replace avatar image for the current user."""
    data = await file.read()
    try:
        user = await user_service.update_avatar(
            current_user.id, data, file.filename or "avatar.jpg", file.content_type or ""
        )
    except ValueError as e:
        raise BadRequestError(message=str(e)) from None
    return user


@router.get("/avatar/{user_id}", response_model=None)
async def get_avatar(user_id: UUID, user_service: UserSvc) -> Any:
    """Get user avatar image."""
    user = await user_service.get_by_id(user_id)
    if not user.avatar_url:
        raise NotFoundError(message="No avatar set")
    file_path = user_service.get_avatar_path(user.avatar_url)
    if not file_path:
        raise NotFoundError(message="Avatar file not found")
    return FileResponse(path=file_path, media_type="image/jpeg")


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
    user_service: UserSvc,
    admin: CurrentAppAdmin,
) -> Any:
    """Update user by ID (admin only)."""
    return await user_service.admin_update(user_id, user_in, acting_admin_id=admin.id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_user_by_id(
    user_id: UUID,
    user_service: UserSvc,
    admin: CurrentAppAdmin,
) -> None:
    """Delete user by ID (admin only)."""
    await user_service.admin_delete(user_id, acting_admin_id=admin.id)
