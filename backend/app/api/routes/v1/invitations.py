"""Invitation routes.

Two keys address the same invitation, because two different people hold them.
An administrator works from the members list and has the id; an invitee has only
the token that arrived in their email. So revoking exists twice: by id under the
organization, and by token for the person the invitation was sent to.

The token itself leaves the building exactly once, in the response to the POST
that mints it. It is a bearer credential - whoever holds one joins the
organization as the role offered to somebody else's address - so nothing reads
it back, and listing invitations returns everything except it.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, InvitationSvc
from app.schemas.organization import (
    InvitationCreate,
    InvitationCreated,
    InvitationList,
    InvitationRead,
    InviteLinkCreate,
)

org_router = APIRouter()
token_router = APIRouter()


@org_router.post(
    "/{org_id}/invitations", response_model=InvitationCreated, status_code=status.HTTP_201_CREATED
)
async def create_invitation(
    org_id: UUID,
    data: InvitationCreate,
    service: InvitationSvc,
    user: CurrentUser,
) -> Any:
    """Invite a user to the organization by email. Requires Owner or Admin.

    The token is shown once, here. It is emailed to the invitee as well; this
    copy is for the inviter, whose mail may not arrive. No later request returns
    it.
    """
    invite = await service.invite(org_id, data.email, data.role, requester_id=user.id)
    return InvitationCreated(
        id=invite.id,
        organization_id=invite.organization_id,
        email=invite.email,
        role=invite.role,
        status=invite.status,
        invitation_token=invite.token,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )


@org_router.post(
    "/{org_id}/invitations/link",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_invite_link(
    org_id: UUID,
    data: InviteLinkCreate,
    service: InvitationSvc,
    user: CurrentUser,
) -> Any:
    """Mint a shareable link. Requires Owner or Admin.

    The token is returned once, here, because a link is only useful if somebody
    can copy it - and it is never returned again: the listing carries no tokens,
    for the same reason it never has.
    """
    invite = await service.create_link(
        org_id,
        data.role,
        requester_id=user.id,
        max_uses=data.max_uses,
        email_domain=data.email_domain,
    )
    return InvitationCreated(
        id=invite.id,
        organization_id=invite.organization_id,
        email=None,
        role=invite.role,
        status=invite.status,
        max_uses=invite.max_uses,
        used_count=invite.used_count,
        email_domain=invite.email_domain,
        invitation_token=invite.token,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )


@org_router.get("/{org_id}/invitations", response_model=InvitationList)
async def list_invitations(
    org_id: UUID,
    service: InvitationSvc,
    user: CurrentUser,
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
) -> Any:
    """List invitations for an organization. Requires Owner or Admin.

    Without the tokens. Revoking from this list goes through the id below.
    """
    invites = await service.list_for_org(
        org_id, user.id, status=status_filter, skip=skip, limit=limit
    )
    items = [
        InvitationRead(
            id=inv.id,
            organization_id=inv.organization_id,
            email=inv.email,
            role=inv.role,
            status=inv.status,
            max_uses=inv.max_uses,
            used_count=inv.used_count,
            reserved_count=len(inv.reserved_emails),
            email_domain=inv.email_domain,
            expires_at=inv.expires_at,
            created_at=inv.created_at,
        )
        for inv in invites
    ]
    return InvitationList(items=items, total=len(items))


@org_router.delete(
    "/{org_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def revoke_invitation_by_id(
    org_id: UUID,
    invitation_id: UUID,
    service: InvitationSvc,
    user: CurrentUser,
) -> None:
    """Revoke a pending invitation from the members list. Requires Owner or Admin.

    Addressed by id rather than by token: an authenticated administrator has no
    reason to put a live credential in a URL, where it reaches server logs and
    browser history. An invitation belonging to another organization answers 404.
    """
    await service.revoke_by_id(org_id, invitation_id, requester_id=user.id)


@token_router.post(
    "/invitations/{token}/accept", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def accept_invitation(
    token: str,
    service: InvitationSvc,
    user: CurrentUser,
) -> None:
    """Accept an invitation token. Adds the current user to the organization."""
    await service.accept(token, accepting_user_id=user.id)


@token_router.delete(
    "/invitations/{token}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def revoke_invitation(
    token: str,
    service: InvitationSvc,
    user: CurrentUser,
) -> None:
    """Revoke a pending invitation by its token - the invitee's route.

    Kept because the token is the only thing an invitee has: the invitation
    arrives by email, and they know neither its id nor the organization it is
    for. Administrators revoke by id above.
    """
    await service.revoke(token, requester_id=user.id)
