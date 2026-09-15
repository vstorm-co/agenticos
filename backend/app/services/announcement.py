"""The app-admin announcement composer (#1598, Decision 5).

The one action in this feature no organization-scoped role can reach -
`CurrentAppAdmin` alone gates the route, never a `Perm`, since every entry in
the permission catalog is resolved against one organization and none of them
can express "every organization".

Sending is three writes in one transaction: the `announcements` row itself
(the audit-adjacent record of what was sent and to whom), one
`notifications` row per resolved recipient through the exact same write path
every other event in this feature uses - an announcement is not a second
mechanism, it is one more producer into the one that already exists - and a
`record_audit` entry, the same as every other privileged action in this
package. Recipients are resolved fresh, not from a stored organization list:
the `"all organizations"` case means everybody who is currently a member of
something, not who was on the day it was sent, which is what makes reading
the audience straight off `Announcement.audience_spec` (rather than off a
snapshot list of ids) also correct for `NotificationCenterService`'s own
read-time recheck (Decision 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import BadRequestError
from app.db.models.announcement import Announcement
from app.db.models.notification import NotificationEventType
from app.repositories import announcement as announcement_repo
from app.repositories import member as member_repo
from app.repositories import organization as organization_repo
from app.services.notification_center import NotificationCenterService


@dataclass(frozen=True)
class AnnouncementSendResult:
    announcement: Announcement
    recipient_count: int


class AnnouncementService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._center = NotificationCenterService(db)

    async def send(
        self,
        *,
        actor_user_id: UUID,
        body: str,
        organizations: Literal["all"] | list[UUID],
        role: str | None,
    ) -> AnnouncementSendResult:
        """Resolve the audience, write the announcement, fan out, and audit it.

        Raises:
            BadRequestError: The resolved audience is empty - an explicit
                organization list naming no current member, or a role
                narrowing nobody in the selected scope holds. A send that
                reaches nobody is refused rather than recorded as sent.
        """
        recipients = await member_repo.list_member_ids_for_audience(
            self.db, organization_ids=organizations, role=role
        )
        if not recipients:
            raise BadRequestError(
                message="This audience currently has no members to reach",
                details={"role": role} if role else {},
            )

        audience_description = await self._describe_audience(organizations, role)
        announcement = await announcement_repo.create(
            self.db,
            actor_user_id=actor_user_id,
            body=body,
            audience_spec={
                "organizations": (
                    "all" if organizations == "all" else [str(org_id) for org_id in organizations]
                ),
                "role": role,
            },
            audience_description=audience_description,
        )

        await self._center.write(
            recipients=list(recipients),
            event_type=NotificationEventType.ANNOUNCEMENT,
            occurrence_id=str(announcement.id),
            summary=body,
            organization_id=None,
            announcement_id=announcement.id,
            actor_user_id=actor_user_id,
        )
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            action="announcement.sent",
            target_type="announcement",
            target_id=str(announcement.id),
            details={
                "audience_description": audience_description,
                "recipient_count": len(recipients),
            },
        )
        return AnnouncementSendResult(announcement=announcement, recipient_count=len(recipients))

    async def _describe_audience(
        self, organizations: Literal["all"] | list[UUID], role: str | None
    ) -> str:
        """The human-readable rendering `Announcement.audience_description`
        stores - computed once at send time so a reader of the audit trail
        is not left decoding `audience_spec`'s JSON to know who was addressed.
        """
        if organizations == "all":
            scope = "All organizations"
        else:
            orgs = await organization_repo.list_by_ids(self.db, organizations)
            scope = ", ".join(sorted(org.name for org in orgs)) or "No organizations"
        return f"{scope} - {role}s" if role else scope
