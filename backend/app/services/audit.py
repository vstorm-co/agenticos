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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from app.core.audit import chain_hash, record_audit
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
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.permissions import AuthContext
    from app.db.models.audit_checkpoint import AppAdminAuditCheckpoint
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


@dataclass(frozen=True)
class ChainBreak:
    """Where a chain stopped verifying, and why.

    Attributes:
        seq: The `seq` the break is about - the entry the walk broke on, or, for a
            truncation, the head `seq` the checkpoint recorded and the chain no
            longer reaches.
        entry_id: That entry's id, so the row itself can be found - None for a
            truncation or whole-chain deletion, where the entry the break names is
            gone.
        reason: What did not hold - a rewritten entry, a broken link, or a chain
            that no longer reaches the checkpoint's high-water mark.
    """

    seq: int
    entry_id: UUID | None
    reason: str


@dataclass(frozen=True)
class ChainVerification:
    """The result of walking one organization's chain.

    Attributes:
        organization_id: The chain's organization, or None for the deployment-wide
            chain - actions with no tenant, such as a deployment settings change,
            an impersonation, or app-admin user management.
        entries_checked: How many entries were walked before it ended or broke.
        first_break: The first entry that did not verify, or None when the whole
            chain is intact.
    """

    organization_id: UUID | None
    entries_checked: int
    first_break: ChainBreak | None


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

    async def verify_chain(self, organization_id: UUID | None) -> ChainVerification:
        """Recompute one organization's chain and report the first break.

        Walks the entries in `seq` order, holding the previous entry's hash. Each
        entry has to agree on two things: that its stored `prev_hash` is the hash
        the walk actually arrived with, and that its stored `entry_hash` is what
        recomputing over its contents produces. The first failure of either is
        returned and the walk stops - a rewritten row diverges its own
        `entry_hash`, and a deleted or reordered one diverges the next entry's
        `prev_hash`.

        The two deletions a bare walk cannot see - the tail truncated, or the whole
        chain gone - are caught by comparing the surviving chain against the
        organization's checkpoint (`AppAdminAuditCheckpoint`, #1648): a head behind
        the checkpoint's `max_seq`, or fewer entries than its `entry_count`, is a
        truncation, and a checkpoint with no chain at all is a deleted chain.

        Detection, not prevention: an operator with the database can rewrite a row
        and every hash after it, and a Postgres superuser can drop the checkpoint's
        guard trigger and delete both the entries and the checkpoint - so a chain
        that verifies is evidence of no tampering by anyone who did not also defeat
        those, not proof of none. `docs/governance.md` states the boundary (#1648).
        """
        # The checkpoint is read *before* the entries, and the comparison below only
        # flags a chain that is behind it. Both reads run under READ COMMITTED, so an
        # audited write committing between them is visible to one and not the other -
        # and in this order that write lands in `entries`, leaving the chain ahead of
        # a checkpoint that has not caught up, which is not a truncation. Reading the
        # checkpoint second inverts it: the chain looks short against a checkpoint
        # that already moved, and `audit-verify` reports an intact trail as tampered.
        checkpoint = await audit_log_repo.checkpoint_for_org(
            self.db, organization_id=organization_id
        )
        entries = await audit_log_repo.chain_for_org(self.db, organization_id=organization_id)
        prev_hash: str | None = None
        for index, entry in enumerate(entries):
            if entry.prev_hash != prev_hash:
                return ChainVerification(
                    organization_id=organization_id,
                    entries_checked=index + 1,
                    first_break=ChainBreak(
                        seq=entry.seq,
                        entry_id=entry.id,
                        reason="prev_hash does not link to the previous entry",
                    ),
                )
            expected = chain_hash(
                prev_hash=prev_hash,
                actor_user_id=entry.actor_user_id,
                impersonator_user_id=entry.impersonator_user_id,
                organization_id=entry.organization_id,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                details=entry.details,
                ip_address=entry.ip_address,
                created_at=entry.created_at,
            )
            if entry.entry_hash != expected:
                return ChainVerification(
                    organization_id=organization_id,
                    entries_checked=index + 1,
                    first_break=ChainBreak(
                        seq=entry.seq,
                        entry_id=entry.id,
                        reason="entry_hash does not match the entry's contents",
                    ),
                )
            prev_hash = entry.entry_hash

        truncation = self._truncation_break(organization_id, entries, checkpoint)
        return ChainVerification(
            organization_id=organization_id,
            entries_checked=len(entries),
            first_break=truncation,
        )

    def _truncation_break(
        self,
        organization_id: UUID | None,
        entries: list[AppAdminAuditLog],
        checkpoint: AppAdminAuditCheckpoint | None,
    ) -> ChainBreak | None:
        """The break a checkpoint reveals that the hash walk cannot: a chain whose
        head is behind the recorded high-water mark, or gone entirely.

        Takes the checkpoint its caller already read rather than reading its own, so
        the two halves of the comparison come from one point in the walk - see
        `verify_chain` for why the order of those reads is what makes a concurrent
        audited write harmless."""
        if checkpoint is None:
            return None
        if not entries:
            return ChainBreak(
                seq=checkpoint.max_seq,
                entry_id=None,
                reason="the entire chain is missing, but a checkpoint records it reached "
                f"seq {checkpoint.max_seq}",
            )
        if entries[-1].seq < checkpoint.max_seq or len(entries) < checkpoint.entry_count:
            return ChainBreak(
                seq=checkpoint.max_seq,
                entry_id=None,
                reason=f"the chain was truncated: its head is seq {entries[-1].seq} with "
                f"{len(entries)} entries, behind the checkpoint's seq {checkpoint.max_seq} "
                f"and {checkpoint.entry_count} entries",
            )
        return None

    async def verify_all_chains(self) -> list[ChainVerification]:
        """Verify every chain the log holds, in a deterministic report order.

        The set is the union of organizations with entries and organizations with a
        checkpoint - the second is what surfaces a chain deleted whole, which has no
        entries left to enumerate. The deployment-wide chain (no organization) sorts
        first; the rest follow by their id, so two runs report in the same order.
        """
        with_entries = await audit_log_repo.distinct_organization_ids(self.db)
        with_checkpoint = await audit_log_repo.distinct_checkpoint_organization_ids(self.db)
        ordered = sorted(
            set(with_entries) | set(with_checkpoint),
            key=lambda oid: (oid is not None, str(oid)),
        )
        return [await self.verify_chain(oid) for oid in ordered]
