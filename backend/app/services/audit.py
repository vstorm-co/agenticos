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

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.audit import chain_hash
from app.repositories import audit_log_repo
from app.schemas.audit import AuditEntryList, AuditEntryRead

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.permissions import AuthContext


@dataclass(frozen=True)
class ChainBreak:
    """Where a chain stopped verifying, and why.

    Attributes:
        seq: The `seq` of the entry the walk broke on - what an operator greps for.
        entry_id: That entry's id, so the row itself can be found.
        reason: Whether the entry's own hash failed to match its contents, or its
            link to the entry before it did.
    """

    seq: int
    entry_id: UUID
    reason: str


@dataclass(frozen=True)
class ChainVerification:
    """The result of walking one organization's chain.

    Attributes:
        organization_id: The chain's organization, or None for the deployment-wide
            chain (the approval-expiry sweep and operator shell commands).
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

    async def verify_chain(self, organization_id: UUID | None) -> ChainVerification:
        """Recompute one organization's chain and report the first break.

        Walks the entries in `seq` order, holding the previous entry's hash. Each
        entry has to agree on two things: that its stored `prev_hash` is the hash
        the walk actually arrived with, and that its stored `entry_hash` is what
        recomputing over its contents produces. The first failure of either is
        returned and the walk stops - a rewritten row diverges its own
        `entry_hash`, and a deleted or reordered one diverges the next entry's
        `prev_hash`.

        Detection, not prevention: an operator with the database can rewrite a row
        and every hash after it, so a chain that verifies is evidence of no
        tampering by anyone who did not also recompute the chain, not proof of
        none. It is also blind to a chain being truncated from the end - dropping
        the newest entries leaves the surviving prefix internally consistent - and
        to a whole organization's chain being deleted, which simply removes it from
        the set walked here; catching either needs a checkpoint kept outside the
        table. `docs/governance.md` states the boundary (#1622).
        """
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
        return ChainVerification(
            organization_id=organization_id,
            entries_checked=len(entries),
            first_break=None,
        )

    async def verify_all_chains(self) -> list[ChainVerification]:
        """Verify every chain the log holds, in a deterministic report order.

        The deployment-wide chain (no organization) sorts first; the rest follow
        by their id, so two runs over the same data report in the same order.
        """
        org_ids = await audit_log_repo.distinct_organization_ids(self.db)
        ordered = sorted(org_ids, key=lambda oid: (oid is not None, str(oid)))
        return [await self.verify_chain(oid) for oid in ordered]
