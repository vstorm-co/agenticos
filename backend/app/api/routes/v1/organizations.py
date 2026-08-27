"""Organization CRUD routes."""

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, OrganizationSvc, OrganizationTeardownSvc
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationList,
    OrganizationRead,
    OrganizationUpdate,
)
from app.services.file_storage import sniff_image_media_type

router = APIRouter()


@router.get("", response_model=OrganizationList)
async def list_organizations(
    service: OrganizationSvc,
    user: CurrentUser,
) -> Any:
    """List all organizations the current user belongs to."""
    return await service.list_readable_for_user(user.id)


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    service: OrganizationSvc,
    user: CurrentUser,
) -> Any:
    """Create a new organization. The requesting user becomes Owner."""
    org = await service.create(data, owner_id=user.id)
    return await service.read_for_user(org.id, user.id)


@router.get("/{org_id}", response_model=OrganizationRead)
async def get_organization(
    org_id: UUID,
    service: OrganizationSvc,
    user: CurrentUser,
) -> Any:
    """Get a single organization the current user is a member of."""
    return await service.read_for_user(org_id, user.id)


@router.patch("/{org_id}", response_model=OrganizationRead)
async def update_organization(
    org_id: UUID,
    data: OrganizationUpdate,
    service: OrganizationSvc,
    user: CurrentUser,
) -> Any:
    """Update organization name or avatar. Requires Admin or Owner role."""
    org = await service.update(org_id, data, requester_id=user.id)
    return await service.read_for_user(org.id, user.id)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_organization(
    org_id: UUID,
    service: OrganizationTeardownSvc,
    user: CurrentUser,
) -> None:
    """Delete an organization. Requires Owner role. Personal orgs cannot be deleted."""
    await service.delete(org_id, requester_id=user.id)


@router.post("/{org_id}/avatar", response_model=OrganizationRead)
async def upload_organization_avatar(
    org_id: UUID,
    service: OrganizationSvc,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> Any:
    """Upload or replace the organization avatar. Requires Admin or Owner role."""
    data = await file.read()
    updated = await service.upload_avatar(
        org_id,
        requester_id=user.id,
        file_data=data,
        content_type=file.content_type,
    )
    return await service.read_for_user(updated.id, user.id)


@router.get("/{org_id}/avatar", response_model=None)
async def get_organization_avatar(
    org_id: UUID,
    service: OrganizationSvc,
    user: CurrentUser,
) -> Any:
    """Stream the organization avatar image. Membership is required to view."""
    org, _ = await service.get_for_user(org_id, user.id)
    if not org.avatar_url:
        raise HTTPException(status_code=404, detail="No avatar set")
    file_path = service.get_avatar_path(org.avatar_url)
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="Avatar file missing")
    # Pinned to an image type, and refused if it is not one: the type was guessed
    # from the stored filename's suffix, and the upload kept whatever suffix the
    # caller chose, so a stored `x.html` was served as `text/html` - a script on
    # the app's own origin rather than a picture (#702).
    media_type = sniff_image_media_type(file_path)
    if media_type is None:
        raise HTTPException(status_code=404, detail="Avatar file missing")
    return FileResponse(
        path=file_path, media_type=media_type, headers={"X-Content-Type-Options": "nosniff"}
    )
