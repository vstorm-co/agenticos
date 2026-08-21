"""Reading the audit log: who did what in this organization.

The log is written by :func:`app.core.audit.record_audit`, called from whichever
service performed the gated mutation, so an action is recorded whether it arrived
over HTTP, through a channel or from a background flow. This is the read half.

It is a service rather than two calls in the route because of what the scope is:
"an entry belongs to exactly one organization" is a property of the log, and the
`/audit` route used to hold it as a keyword argument it filled in itself. A scope
a handler owns is a scope no service test can see, and the next reader of this
entity - an export, a channel command, an admin page - would have had to know to
pass the same thing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.repositories import audit_log_repo
from app.schemas.audit import AuditEntryList, AuditEntryRead

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.permissions import AuthContext


class AuditService:
    """The audit trail of one organization, read for whoever may see it.

    Attributes:
        db: The request-scoped session every read runs in.

    Example:
        ```python
        entries = await AuditService(db).list_for_organization(ctx, limit=50)
        ```
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_organization(
        self, ctx: AuthContext, *, skip: int = 0, limit: int = 50
    ) -> AuditEntryList:
        """This organization's entries, newest first, and how many there are.

        The organization comes off the auth context rather than from an argument:
        the caller cannot ask for another tenant's trail by passing a different
        id, because there is nowhere to pass one.

        `total` is a second query rather than `len(items)`. A page is not a total,
        and a client paging through the log needs to know how far it goes - which
        is also why the count is unconditional even when the first page is short.
        """
        entries = await audit_log_repo.list_for_org(
            self.db, organization_id=ctx.organization_id, skip=skip, limit=limit
        )
        total = await audit_log_repo.count_for_org(self.db, organization_id=ctx.organization_id)
        return AuditEntryList(
            items=[
                AuditEntryRead(
                    id=entry.id,
                    actor_user_id=entry.actor_user_id,
                    impersonator_user_id=entry.impersonator_user_id,
                    action=entry.action,
                    target_type=entry.target_type,
                    target_id=entry.target_id,
                    details=entry.details,
                    created_at=entry.created_at,
                )
                for entry in entries
            ],
            total=total,
        )
