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
from app.services.file_storage import image_media_type_for

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
    """
    return await user_service.update(current_user.id, user_in)


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
    file_path = user_service.get_avatar_path(user.avatar_url)
    if not file_path:
        raise NotFoundError(message="Avatar file not found")
    # Pinned to the file's actual image type, and refused if it is not an image at
    # all: the avatar is served from the app's own origin, and the upload kept
    # whatever suffix the caller's filename had (#702). Hardcoding image/jpeg here
    # named a lie for a stored png and, worse, said nothing about a stored .html.
    media_type = image_media_type_for(file_path)
    if media_type is None:
        raise NotFoundError(message="Avatar file not found")
    return FileResponse(
        path=file_path, media_type=media_type, headers={"X-Content-Type-Options": "nosniff"}
    )


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
    _: CurrentAppAdmin,
) -> Any:
    """Update user by ID (admin only)."""
    return await user_service.update(user_id, user_in)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_user_by_id(
    user_id: UUID,
    user_service: UserSvc,
    _: CurrentAppAdmin,
) -> None:
    """Delete user by ID (admin only)."""
    await user_service.delete(user_id)
