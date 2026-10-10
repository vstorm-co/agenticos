"""Group routes (nested under /orgs/{org_id}/groups).

Shaped like the member routes beside them: the organization is the one in the
path, and `GroupService` decides from the caller's membership there - any member
may read, `members:manage` may change.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import GroupSvc, PathOrgAuth, require_in_path_org
from app.api.public_api import PUBLIC
from app.core.permissions import Perm
from app.schemas.group import (
    GroupCreate,
    GroupList,
    GroupMemberAdd,
    GroupMemberList,
    GroupMemberRead,
    GroupRead,
    GroupResourceList,
    GroupUpdate,
    as_group_icon,
)

router = APIRouter(dependencies=[PUBLIC])

_MANAGE = Depends(require_in_path_org(Perm.MEMBERS_MANAGE))


@router.get("/{org_id}/groups", response_model=GroupList)
async def list_groups(org_id: UUID, service: GroupSvc, ctx: PathOrgAuth) -> Any:
    """Every group in the organization, with its member count. Any member may call this."""
    rows = await service.list_groups(org_id, ctx.subject_id)
    items = [
        GroupRead(
            id=group.id,
            organization_id=group.organization_id,
            name=group.name,
            description=group.description,
            icon=as_group_icon(group.icon),
            member_count=count,
            created_at=group.created_at,
        )
        for group, count in rows
    ]
    return GroupList(items=items, total=len(items))


@router.post(
    "/{org_id}/groups",
    response_model=GroupRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
)
async def create_group(org_id: UUID, data: GroupCreate, service: GroupSvc, ctx: PathOrgAuth) -> Any:
    """Create a group. Requires `members:manage`."""
    group = await service.create(org_id, ctx.subject_id, data)
    return GroupRead(
        id=group.id,
        organization_id=group.organization_id,
        name=group.name,
        description=group.description,
        icon=as_group_icon(group.icon),
        member_count=0,
        created_at=group.created_at,
    )


@router.patch("/{org_id}/groups/{group_id}", response_model=GroupRead, dependencies=[_MANAGE])
async def update_group(
    org_id: UUID, group_id: UUID, data: GroupUpdate, service: GroupSvc, ctx: PathOrgAuth
) -> Any:
    """Rename a group or change its description. Requires `members:manage`."""
    group, count = await service.update(org_id, group_id, ctx.subject_id, data)
    return GroupRead(
        id=group.id,
        organization_id=group.organization_id,
        name=group.name,
        description=group.description,
        icon=as_group_icon(group.icon),
        member_count=count,
        created_at=group.created_at,
    )


@router.delete(
    "/{org_id}/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[_MANAGE],
)
async def delete_group(org_id: UUID, group_id: UUID, service: GroupSvc, ctx: PathOrgAuth) -> None:
    """Delete a group, the grants made to it and the mappings naming it. Requires `members:manage`."""
    await service.delete(org_id, group_id, ctx.subject_id)


@router.get("/{org_id}/groups/{group_id}/resources", response_model=GroupResourceList)
async def list_group_resources(
    org_id: UUID, group_id: UUID, service: GroupSvc, ctx: PathOrgAuth
) -> Any:
    """What a group has been given - agents, knowledge bases, skills, context and apps.

    Narrowed to what the caller may see. Any member may call this.
    """
    items = await service.resources(ctx, group_id)
    return GroupResourceList(items=items, total=len(items))


@router.get("/{org_id}/groups/{group_id}/members", response_model=GroupMemberList)
async def list_group_members(
    org_id: UUID, group_id: UUID, service: GroupSvc, ctx: PathOrgAuth
) -> Any:
    """Who is in one group, and whether the directory or a person put them there."""
    rows = await service.list_members(org_id, group_id, ctx.subject_id)
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
    dependencies=[_MANAGE],
)
async def add_group_member(
    org_id: UUID, group_id: UUID, data: GroupMemberAdd, service: GroupSvc, ctx: PathOrgAuth
) -> Any:
    """Put a member of the organization in the group. Requires `members:manage`."""
    member, email, full_name = await service.add_member(
        org_id, group_id, data.user_id, ctx.subject_id
    )
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
    dependencies=[_MANAGE],
)
async def remove_group_member(
    org_id: UUID, group_id: UUID, member_user_id: UUID, service: GroupSvc, ctx: PathOrgAuth
) -> None:
    """Take somebody out of the group. Requires `members:manage`."""
    await service.remove_member(org_id, group_id, member_user_id, ctx.subject_id)
