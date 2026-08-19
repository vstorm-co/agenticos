import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AlreadyExistsError,
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.permissions import OrgRoleName, Perm, role_has
from app.db.models.organization import Invitation, InvitationStatus, OrgRole
from app.repositories import invitation_repo, member_repo, organization_repo, user_repo
from app.services.deployment_settings import DeploymentSettingsService
from app.services.email.service import get_email_service

logger = logging.getLogger(__name__)

# Roles an admin may invite into. Owner and admin are excluded: inviting a peer
# to your own level is an ownership decision.
_ADMIN_INVITABLE_ROLES = {
    OrgRoleName.BUILDER.value,
    OrgRoleName.OPERATOR.value,
    OrgRoleName.MEMBER.value,
    OrgRoleName.VIEWER.value,
}


class InvitationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def invite(
        self,
        organization_id: UUID,
        email: str,
        role: str,
        requester_id: UUID,
    ):
        requester = await member_repo.get(
            self.db, organization_id=organization_id, user_id=requester_id
        )
        if not requester or not role_has(requester.role, Perm.MEMBERS_MANAGE):
            raise AuthorizationError(message="Only Owner or Admin can invite members")

        if requester.role == OrgRole.ADMIN.value and role not in _ADMIN_INVITABLE_ROLES:
            raise AuthorizationError(message="Admin can only invite as Member or Viewer")

        normalized_email = email.lower()

        existing_user = await user_repo.get_by_email(self.db, normalized_email)
        if existing_user:
            existing_membership = await member_repo.get(
                self.db, organization_id=organization_id, user_id=existing_user.id
            )
            if existing_membership:
                raise AlreadyExistsError(
                    message="User is already a member of this organization",
                    details={"email": normalized_email},
                )

        pending = await invitation_repo.get_pending_for_org_email(
            self.db, organization_id=organization_id, email=normalized_email
        )
        if pending:
            raise AlreadyExistsError(
                message="A pending invitation already exists for this email",
                details={"email": normalized_email},
            )

        invite = await invitation_repo.create(
            self.db,
            organization_id=organization_id,
            email=normalized_email,
            role=role,
            invited_by_user_id=requester_id,
        )
        logger.info(
            "Invitation created for %s to org %s (role=%s) by user %s",
            normalized_email,
            organization_id,
            role,
            requester_id,
        )
        try:
            org = await organization_repo.get_by_id(self.db, organization_id)
            requester_user = await user_repo.get_by_id(self.db, requester_id)
            frontend = settings.FRONTEND_URL.rstrip("/")
            accept_url = f"{frontend}/invitations/{invite.token}"
            await get_email_service().send_invitation(
                to=normalized_email,
                inviter_name=(requester_user.full_name or requester_user.email)
                if requester_user
                else "A team member",
                org_name=org.name if org else "the organization",
                accept_url=accept_url,
                app_name=await DeploymentSettingsService(self.db).effective_app_name(),
            )
        except Exception:
            logger.exception("email_invitation_failed")
        return invite

    async def create_link(
        self,
        organization_id: UUID,
        role: str,
        requester_id: UUID,
        *,
        max_uses: int | None = None,
        email_domain: str | None = None,
    ) -> Invitation:
        """A shareable link that admits whoever holds it, up to its limits.

        The same permission and the same role ceiling as an email invitation: an
        Admin cannot mint a link that grants more than an Admin may invite, or
        the link would be a way around the ceiling rather than a convenience.

        Args:
            max_uses: How many people it admits; None is unlimited.
            email_domain: Restrict to addresses at this domain. An unlimited
                link with no domain is defensible only when the URL itself is
                treated as a secret, which a link pasted into a channel is not.
        """
        requester = await member_repo.get(
            self.db, organization_id=organization_id, user_id=requester_id
        )
        if not requester or not role_has(requester.role, Perm.MEMBERS_MANAGE):
            raise AuthorizationError(message="Only Owner or Admin can invite members")
        if requester.role == OrgRole.ADMIN.value and role not in _ADMIN_INVITABLE_ROLES:
            raise AuthorizationError(message="Admin can only invite as Member or Viewer")

        invite = await invitation_repo.create(
            self.db,
            organization_id=organization_id,
            email=None,
            role=role,
            invited_by_user_id=requester_id,
            max_uses=max_uses,
            email_domain=(email_domain or "").lstrip("@").lower() or None,
        )
        logger.info(
            "Invite link created for org %s (role=%s, max_uses=%s, domain=%s) by user %s",
            organization_id,
            role,
            max_uses,
            email_domain,
            requester_id,
        )
        return invite

    async def list_for_org(
        self,
        organization_id: UUID,
        requester_id: UUID,
        *,
        status: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ):
        requester = await member_repo.get(
            self.db, organization_id=organization_id, user_id=requester_id
        )
        if not requester or not role_has(requester.role, Perm.MEMBERS_MANAGE):
            raise AuthorizationError(message="Only Owner or Admin can view invitations")

        return await invitation_repo.list_for_org(
            self.db, organization_id, status=status, skip=skip, limit=limit
        )

    async def accept(self, token: str, accepting_user_id: UUID):
        invite = await invitation_repo.get_by_token(self.db, token)
        if not invite:
            raise NotFoundError(message="Invitation not found or already used")

        if invite.status != InvitationStatus.PENDING.value:
            raise BadRequestError(
                message="Invitation is no longer valid",
                details={"status": invite.status},
            )

        if invite.expires_at and invite.expires_at < datetime.now(UTC):
            # Expired, not revoked: `revoked` records a withdrawal somebody
            # made, and this row timed out with nobody acting on it (#456).
            await invitation_repo.expire(self.db, invite)
            raise BadRequestError(message="Invitation has expired")

        accepting_user = await user_repo.get_by_id(self.db, accepting_user_id)
        if accepting_user is None:
            raise AuthenticationError(message="Sign in to accept this invitation.")

        if invite.email is not None:
            if accepting_user.email.lower() != invite.email:
                raise AuthenticationError(
                    message="This invitation was sent to a different email address."
                )
        else:
            # A link. Its guards are its own: how many people it admits, and
            # whose addresses. Checked here rather than at creation because both
            # are questions about the person arriving, not about the link.
            # Counting reservations too, minus this person's own: a use held for
            # somebody who registered under the link is spent, and a use held *for
            # them* must not refuse the acceptance it was reserved for.
            held = [
                address
                for address in invite.reserved_emails
                if address != accepting_user.email.lower()
            ]
            if invite.max_uses is not None and invite.used_count + len(held) >= invite.max_uses:
                raise BadRequestError(message="This invite link has been used up")
            if invite.email_domain and not accepting_user.email.lower().endswith(
                f"@{invite.email_domain}"
            ):
                raise AuthenticationError(
                    message=f"This link is only for @{invite.email_domain} addresses."
                )

        existing = await member_repo.get(
            self.db, organization_id=invite.organization_id, user_id=accepting_user_id
        )
        if existing:
            raise AlreadyExistsError(
                message="You are already a member of this organization",
                details={"org_id": str(invite.organization_id)},
            )
        org = await organization_repo.get_by_id(self.db, invite.organization_id)
        seats_limit = getattr(org, "seats_limit", None) if org is not None else None
        if seats_limit is not None:
            current_count = await member_repo.count_for_org(self.db, invite.organization_id)
            if current_count >= seats_limit:
                raise PaymentRequiredError(
                    message="Seat limit reached - upgrade your plan to add more members",
                    details={"seats_limit": seats_limit, "current": current_count},
                )
        await member_repo.create(
            self.db,
            organization_id=invite.organization_id,
            user_id=accepting_user_id,
            role=invite.role,
        )
        if invite.email is None:
            # A link stays open for the next person; an email invitation is
            # spent. Marking a link accepted on its first use would make it a
            # one-shot URL that looked like a link.
            #
            # The address releases whatever reservation it made when it registered,
            # in the same step - so the use a registration held becomes the use this
            # acceptance counts rather than a second one.
            await invitation_repo.record_use(self.db, invite, email=accepting_user.email)
        else:
            await invitation_repo.accept(self.db, invite, accepted_by_user_id=accepting_user_id)
        logger.info(
            "Invitation %s accepted by user %s (org %s)",
            invite.id,
            accepting_user_id,
            invite.organization_id,
        )
        return invite

    async def expire_stale(self) -> int:
        """Mark every PENDING invitation past its expiry as EXPIRED.

        An invitation ordinarily times out by nobody clicking it, so no request
        path can be relied on to write `EXPIRED` - without a schedule the row
        stays `pending` for ever and the pending list keeps offering it. The
        sweep reads across every organization because a schedule has no tenant
        to be scoped to; all it writes is a status the row already promised.

        Returns:
            How many invitations were expired. Zero on the ordinary sweep,
            which is why the flow logs only when it is not.
        """
        return await invitation_repo.expire_stale(self.db)

    async def revoke_by_id(
        self, organization_id: UUID, invitation_id: UUID, requester_id: UUID
    ) -> Invitation:
        """Revoke from the members list, addressing the invitation by its id.

        The administrator's half of revoking. They are looking at the list, so
        they have the id, and asking them for the token instead would put a live
        bearer credential in the path of an authenticated request - server logs,
        browser history, and any proxy in between.

        An invitation belonging to another organization is reported as missing
        rather than forbidden, so ids stay unprobeable. The role is checked
        before the status, so a member without `members:manage` is refused
        rather than told what state somebody else's invitation is in.
        """
        invite = await invitation_repo.get_by_id(self.db, invitation_id)
        if not invite or invite.organization_id != organization_id:
            raise NotFoundError(message="Invitation not found")

        requester = await member_repo.get(
            self.db, organization_id=organization_id, user_id=requester_id
        )
        if not requester or not role_has(requester.role, Perm.MEMBERS_MANAGE):
            raise AuthorizationError(message="Only Owner or Admin can revoke invitations")

        if invite.status != InvitationStatus.PENDING.value:
            raise BadRequestError(
                message="Only pending invitations can be revoked",
                details={"status": invite.status},
            )

        await invitation_repo.revoke(self.db, invite)
        logger.info(
            "Invitation %s revoked by user %s (org %s)", invite.id, requester_id, organization_id
        )
        return invite

    async def revoke(self, token: str, requester_id: UUID):
        """Revoke by token, which is all an invitee has.

        Invitees can revoke their own invitation - not just OWNER/ADMIN. The
        invitation reaches them by email and nothing else about it does: no id,
        no organization. Administrators use :meth:`revoke_by_id` instead.
        """
        invite = await invitation_repo.get_by_token(self.db, token)
        if not invite:
            raise NotFoundError(message="Invitation not found")

        if invite.status != InvitationStatus.PENDING.value:
            raise BadRequestError(
                message="Only pending invitations can be revoked",
                details={"status": invite.status},
            )

        requester = await member_repo.get(
            self.db, organization_id=invite.organization_id, user_id=requester_id
        )
        accepting_user = await user_repo.get_by_id(self.db, requester_id)
        is_own_invite = accepting_user and accepting_user.email.lower() == invite.email

        if not is_own_invite and (
            not requester or not role_has(requester.role, Perm.MEMBERS_MANAGE)
        ):
            raise AuthorizationError(message="Only Owner or Admin can revoke invitations")

        await invitation_repo.revoke(self.db, invite)
        return invite
