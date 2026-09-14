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

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from app.core.audit import record_audit
from app.repositories import audit_log_repo
from app.schemas.audit import AuditEntryList, AuditEntryRead
from app.services.exporting import (
    MAX_EXPORT_ROWS,
    ExportResult,
    cell,
    csv_document,
    guard_cap,
    jsonl_document,
    require_range,
    stamp,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.permissions import AuthContext
    from app.db.models.audit_log import AppAdminAuditLog

# What the export ships, matching the fields the read model exposes on the tab -
# `ip_address` is stored but not surfaced there, so it is not exported either
# (the same "exactly what the tab shows" rule the run export follows).
_AUDIT_HEADER = [
    "entry_id",
    "created_at",
    "actor_user_id",
    "impersonator_user_id",
    "action",
    "target_type",
    "target_id",
    "details",
]


def _audit_row(entry: AppAdminAuditLog) -> list[object]:
    """One entry as CSV cells, `details` flattened to a JSON string for the sheet."""
    return [
        entry.id,
        entry.created_at,
        entry.actor_user_id,
        entry.impersonator_user_id,
        entry.action,
        entry.target_type,
        entry.target_id,
        None if entry.details is None else json.dumps(entry.details, sort_keys=True),
    ]


def _audit_record(entry: AppAdminAuditLog) -> dict[str, Any]:
    """One entry as a JSON object, `details` kept as a nested object."""
    return {
        "entry_id": entry.id,
        "created_at": entry.created_at,
        "actor_user_id": entry.actor_user_id,
        "impersonator_user_id": entry.impersonator_user_id,
        "action": entry.action,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "details": entry.details,
    }


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

    async def export(
        self,
        ctx: AuthContext,
        *,
        since: datetime | None,
        until: datetime | None,
        fmt: Literal["csv", "jsonl"],
    ) -> ExportResult:
        """This organization's audit entries in a window, as a downloadable file.

        The same `audit:read` gate and organization scope as the list, with two
        differences an export demands: the date range is **mandatory**, and a match
        over the row cap is **refused** rather than paged, because an export has no
        ceiling by nature. CSV for a spreadsheet, JSONL for a log pipeline; the two
        describe the same rows, `details` flattened to a JSON string in the sheet
        and kept as a nested object in the lines.

        The export writes its own audit entry. Reading a whole trail is a
        privileged act, and the record of who took it away is the first thing a
        later reader of that trail wants - it names the window, the format and the
        row count, never a row.
        """
        start, end = require_range(since, until)
        entries, total = await audit_log_repo.list_in_window_for_org(
            self.db,
            organization_id=ctx.organization_id,
            since=start,
            until=end,
            limit=MAX_EXPORT_ROWS,
        )
        guard_cap(total, remedy="Narrow the date range and try again.")

        now = datetime.now(UTC)
        if fmt == "jsonl":
            content = jsonl_document([_audit_record(entry) for entry in entries])
        else:
            content = csv_document(_AUDIT_HEADER, [_audit_row(entry) for entry in entries])

        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="audit.export",
            target_type="audit_log",
            details={
                "since": cell(start),
                "until": cell(end),
                "format": fmt,
                "row_count": len(entries),
            },
        )
        return ExportResult(
            content=content, filename=stamp("audit", now, fmt), row_count=len(entries)
        )
