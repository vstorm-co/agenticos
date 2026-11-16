"""Telling people that a workflow step is waiting on their approval."""

import hashlib
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ROLE_PERMS, Perm, role_has
from app.db.models.notification import NotificationChannel, NotificationEventType
from app.repositories import member as member_repo
from app.services.notification_center import NotificationCenterService
from app.services.workflow_execution import context
from app.services.workflow_execution.approval_audience import group_approvers

_DECIDING_ROLES = [role for role in ROLE_PERMS if role_has(role, Perm.APPROVALS_DECIDE)]


async def notify_approvers(
    db: AsyncSession,
    *,
    title: str,
    approvers: Sequence[UUID],
    approver_groups: Sequence[UUID] = (),
) -> None:
    """Tell whoever may decide the current step's approval that it waits on them.

    The named approvers and the deciding members of the named groups when the
    step names either. Otherwise anyone in the organization who holds
    `approvals:decide` may decide, app admins among the members included, so
    that is who is told. The row opens the approvals queue, in the organization
    the run belongs to.
    """
    current = context.current()
    if approvers or approver_groups:
        recipients = list(dict.fromkeys(approvers))
        if approver_groups:
            in_groups = await group_approvers(
                db, organization_id=current.organization_id, group_ids=list(approver_groups)
            )
            recipients += sorted(in_groups.difference(recipients), key=str)
    else:
        recipients = await member_repo.list_member_ids_by_role(
            db,
            organization_id=current.organization_id,
            roles=_DECIDING_ROLES,
            with_app_admins=True,
        )
    if not recipients:
        return
    await NotificationCenterService(db).write(
        recipients=recipients,
        event_type=NotificationEventType.WORKFLOW_NOTIFICATION,
        occurrence_id="workflow-approval:"
        + hashlib.sha256(current.idempotency_key.encode()).hexdigest(),
        summary=f"Approval needed: {title}",
        context_url=f"/runs?tab=approvals&org={current.organization_id}",
        render_context={"approval_title": title},
        organization_id=current.organization_id,
        actor_user_id=current.auth.user_id,
        channels={NotificationChannel.IN_APP},
    )
