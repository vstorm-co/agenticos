"""Group routes (nested under /orgs/{org_id}/groups).

Shaped like the member routes beside them: the organization is the one in the
path, and `GroupService` decides from the caller's membership there - any member
may read, `members:manage` may change.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, GroupSvc
from app.schemas.group import (
    GroupCreate,
    GroupList,
    GroupMemberAdd,
    GroupMemberList,
    GroupMemberRead,
    GroupRead,
    GroupUpdate,
)

router = APIRouter()


@router.get("/{org_id}/groups", response_model=GroupList)
async def list_groups(org_id: UUID, service: GroupSvc, user: CurrentUser) -> Any:
    """Every group in the organization, with its member count. Any member may call this."""
    rows = await service.list_groups(org_id, user.id)
    items = [
        GroupRead(
            id=group.id,
            organization_id=group.organization_id,
            name=group.name,
            description=group.description,
            member_count=count,
            created_at=group.created_at,
        )
        for group, count in rows
    ]
    return GroupList(items=items, total=len(items))


@router.post("/{org_id}/groups", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    org_id: UUID, data: GroupCreate, service: GroupSvc, user: CurrentUser
) -> Any:
    """Create a group. Requires `members:manage`."""
    group = await service.create(org_id, user.id, data)
    return GroupRead(
        id=group.id,
        organization_id=group.organization_id,
        name=group.name,
        description=group.description,
        member_count=0,
        created_at=group.created_at,
    )


@router.patch("/{org_id}/groups/{group_id}", response_model=GroupRead)
async def update_group(
    org_id: UUID, group_id: UUID, data: GroupUpdate, service: GroupSvc, user: CurrentUser
) -> Any:
    """Rename a group or change its description. Requires `members:manage`."""
    group, count = await service.update(org_id, group_id, user.id, data)
    return GroupRead(
        id=group.id,
        organization_id=group.organization_id,
        name=group.name,
        description=group.description,
        member_count=count,
        created_at=group.created_at,
    )


@router.delete(
    "/{org_id}/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_group(org_id: UUID, group_id: UUID, service: GroupSvc, user: CurrentUser) -> None:
    """Delete a group, the grants made to it and the mappings naming it. Requires `members:manage`."""
    await service.delete(org_id, group_id, user.id)


@router.get("/{org_id}/groups/{group_id}/members", response_model=GroupMemberList)
async def list_group_members(
    org_id: UUID, group_id: UUID, service: GroupSvc, user: CurrentUser
) -> Any:
    """Who is in one group, and whether the directory or a person put them there."""
    rows = await service.list_members(org_id, group_id, user.id)
    items = [
        GroupMemberRead(
            user_id=member.user_id,
            email=email,
            full_name=full_name,
            source=member.source,
            created_at=member.created_at,
        )
        for member, email, full_name in rows
    ]
    return GroupMemberList(items=items, total=len(items))


@router.post(
    "/{org_id}/groups/{group_id}/members",
    response_model=GroupMemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_group_member(
    org_id: UUID, group_id: UUID, data: GroupMemberAdd, service: GroupSvc, user: CurrentUser
) -> Any:
    """Put a member of the organization in the group. Requires `members:manage`."""
    member, email, full_name = await service.add_member(org_id, group_id, data.user_id, user.id)
    return GroupMemberRead(
        user_id=member.user_id,
        email=email,
        full_name=full_name,
        source=member.source,
        created_at=member.created_at,
    )


@router.delete(
    "/{org_id}/groups/{group_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def remove_group_member(
    org_id: UUID, group_id: UUID, member_user_id: UUID, service: GroupSvc, user: CurrentUser
) -> None:
    """Take somebody out of the group. Requires `members:manage`."""
    await service.remove_member(org_id, group_id, member_user_id, user.id)
