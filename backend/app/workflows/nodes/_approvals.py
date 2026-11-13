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

_DECIDING_ROLES = [role for role in ROLE_PERMS if role_has(role, Perm.APPROVALS_DECIDE)]


async def notify_approvers(db: AsyncSession, *, title: str, approvers: Sequence[UUID]) -> None:
    """Tell whoever may decide the current step's approval that it waits on them.

    The named approvers when the step names any. Otherwise anyone may decide who
    holds `approvals:decide` in the organization, so that is who is told: a step
    naming nobody used to notify nobody, and waited where only Activity showed it.
    The row opens the approvals queue, in the organization the run belongs to.
    """
    current = context.current()
    recipients = list(dict.fromkeys(approvers)) or await member_repo.list_member_ids_by_role(
        db, organization_id=current.organization_id, roles=_DECIDING_ROLES
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
