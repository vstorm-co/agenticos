"""Member management routes (nested under /orgs/{org_id}/members)."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, MemberSvc, PathOrgAuth, require_in_path_org
from app.api.public_api import INTERNAL, PUBLIC
from app.core.permissions import Perm
from app.schemas.organization import (
    OrganizationMemberList,
    OrganizationMemberRead,
    OrganizationMemberUpdate,
    TransferOwnershipRequest,
)

router = APIRouter(dependencies=[PUBLIC])


@router.get("/{org_id}/members", response_model=OrganizationMemberList)
async def list_members(
    org_id: UUID,
    service: MemberSvc,
    ctx: PathOrgAuth,
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
) -> Any:
    """List members of an organization. Any member may call this."""
    rows, total = await service.list_for_org(org_id, ctx.subject_id, skip=skip, limit=limit)
    items = [
        OrganizationMemberRead(
            id=m.id,
            organization_id=m.organization_id,
            user_id=m.user_id,
            role=m.role,
            email=email,
            full_name=full_name,
            avatar_url=avatar_url,
            avatar_color=avatar_color,
            joined_at=m.joined_at,
            source=m.source,
            can_change_role=can_change_role,
        )
        for m, email, full_name, avatar_url, avatar_color, can_change_role in rows
    ]
    return OrganizationMemberList(items=items, total=total)


@router.patch(
    "/{org_id}/members/{target_user_id}",
    response_model=OrganizationMemberRead,
    dependencies=[Depends(require_in_path_org(Perm.MEMBERS_MANAGE))],
)
async def update_member_role(
    org_id: UUID,
    target_user_id: UUID,
    data: OrganizationMemberUpdate,
    service: MemberSvc,
    ctx: PathOrgAuth,
) -> Any:
    """Change a member's role. Requires Owner or Admin."""
    member, email, full_name, avatar_url, avatar_color = await service.change_role(
        org_id, target_user_id, data.role, requester_id=ctx.subject_id
    )
    return OrganizationMemberRead(
        id=member.id,
        organization_id=member.organization_id,
        user_id=member.user_id,
        role=member.role,
        email=email,
        full_name=full_name,
        avatar_url=avatar_url,
        avatar_color=avatar_color,
        joined_at=member.joined_at,
        source=member.source,
    )


@router.delete(
    "/{org_id}/members/{target_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_in_path_org(Perm.MEMBERS_MANAGE))],
)
async def remove_member(
    org_id: UUID,
    target_user_id: UUID,
    service: MemberSvc,
    ctx: PathOrgAuth,
) -> None:
    """Remove a member from the organization. Requires Owner or Admin."""
    await service.remove(org_id, target_user_id, requester_id=ctx.subject_id)


# A person leaving, or handing over ownership, is a decision about themselves and
# not something to delegate to a script: these stay session-only (#2057).
@router.post(
    "/{org_id}/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    openapi_extra=INTERNAL,
)
async def leave_organization(
    org_id: UUID,
    service: MemberSvc,
    user: CurrentUser,
) -> None:
    """Leave an organization. Owner must transfer ownership first if others remain."""
    await service.leave(org_id, requester_id=user.id)


@router.post(
    "/{org_id}/transfer-ownership",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    openapi_extra=INTERNAL,
)
async def transfer_ownership(
    org_id: UUID,
    data: TransferOwnershipRequest,
    service: MemberSvc,
    user: CurrentUser,
) -> None:
    """Transfer Owner role to another member. Caller becomes Admin."""
    await service.transfer_ownership(org_id, data.new_owner_user_id, requester_id=user.id)
