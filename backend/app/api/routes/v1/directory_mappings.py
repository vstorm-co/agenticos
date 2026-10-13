"""Directory group mapping routes (nested under /orgs/{org_id}/directory-mappings).

Which directory groups reach this organization, with which role, and into which
group. `DirectoryMappingService` decides from the caller's membership: reading
takes `members:manage`, changing takes `roles:manage` as well.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DirectoryMappingSvc
from app.schemas.directory import (
    DirectoryMappingCreate,
    DirectoryMappingList,
    DirectoryMappingRead,
)

router = APIRouter()


@router.get("/{org_id}/directory-mappings", response_model=DirectoryMappingList)
async def list_directory_mappings(
    org_id: UUID, service: DirectoryMappingSvc, user: CurrentUser
) -> Any:
    """Every directory group this organization maps. Requires `members:manage`."""
    rows = await service.list_mappings(org_id, user.id)
    items = [
        DirectoryMappingRead(
            id=mapping.id,
            organization_id=mapping.organization_id,
            external_group=mapping.external_group,
            role=mapping.role,
            group_id=mapping.group_id,
            group_name=group_name,
            created_at=mapping.created_at,
        )
        for mapping, group_name in rows
    ]
    return DirectoryMappingList(items=items, total=len(items))


@router.post(
    "/{org_id}/directory-mappings",
    response_model=DirectoryMappingRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_directory_mapping(
    org_id: UUID, data: DirectoryMappingCreate, service: DirectoryMappingSvc, user: CurrentUser
) -> Any:
    """Map a directory group to a role, and optionally a group, here.

    Requires `members:manage` and `roles:manage`, and a role the caller's own
    strictly outranks.
    """
    mapping, group_name = await service.create(org_id, user.id, data)
    return DirectoryMappingRead(
        id=mapping.id,
        organization_id=mapping.organization_id,
        external_group=mapping.external_group,
        role=mapping.role,
        group_id=mapping.group_id,
        group_name=group_name,
        created_at=mapping.created_at,
    )


@router.delete(
    "/{org_id}/directory-mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_directory_mapping(
    org_id: UUID, mapping_id: UUID, service: DirectoryMappingSvc, user: CurrentUser
) -> None:
    """Delete a mapping. The people it placed leave at their next sign-in, unless taken over."""
    await service.delete(org_id, mapping_id, user.id)
