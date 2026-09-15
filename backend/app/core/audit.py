"""Audit log helpers for recording privileged actions."""

import hashlib
import json
import logging
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import LockScope, hold_subject
from app.db.models.audit_log import AppAdminAuditLog

logger = logging.getLogger(__name__)

# The lock subject for entries that belong to no organization - deployment-wide
# actions with no tenant: a deployment settings change, an impersonation starting
# or ending, and app-admin user management. (The expiry sweep and the RAG shell
# commands have a null *actor* but still carry their row's organization, so they
# chain under that tenant, not here.) `hold_subject` takes a UUID, and the all-zeros
# one is not a real organization's id, so it names the deployment-wide chain without
# colliding with any tenant's (#1622).
_DEPLOYMENT_CHAIN = uuid.UUID(int=0)

_impersonator_id: ContextVar[UUID | None] = ContextVar("audit_impersonator_id", default=None)
"""The administrator acting behind the current request's subject, or None.

Set by the auth dependency when the access token carries an `act` claim, read by
:func:`record_audit`. A context variable rather than an argument threaded through
every call site because the actor behind an impersonated request is a property of
the request, not of the mutation - and every service that records an action would
otherwise have to learn to carry it. Each request runs in its own task, so the
value is isolated to that request and its background children (#943).
"""


def set_impersonator(impersonator_id: UUID | None) -> None:
    """Record who is acting behind this request's subject, for the audit trail."""
    _impersonator_id.set(impersonator_id)


def current_impersonator() -> UUID | None:
    """The administrator acting behind this request's subject, or None.

    Used when minting a token so a nested impersonation keeps naming the human
    who started the chain rather than the account one hop up it (#943).
    """
    return _impersonator_id.get()


def chain_hash(
    *,
    prev_hash: str | None,
    actor_user_id: UUID | None,
    impersonator_user_id: UUID | None,
    organization_id: UUID | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    details: dict[str, Any] | None,
    ip_address: str | None,
    created_at: datetime,
) -> str:
    """The hash that links one audit entry to the previous one in its chain.

    `SHA-256(prev_hash || canonical fields)`: the previous entry's hash folded in,
    so changing an earlier entry, or reordering, inserting or deleting one from the
    middle, diverges every hash after it - which is what `agenticos cmd audit-verify`
    detects. Dropping the newest entries or a whole organization's chain is the case
    it cannot see on its own, since the survivors stay internally consistent. The
    one definition, imported by `record_audit`, the backfill migration and the
    verifier alike, because three copies of a hash function are three chances for
    them to disagree and call an untampered trail broken.

    `created_at` is normalized to UTC and the payload is sorted, so the string
    hashed is the same whether the value was just built in Python or read back
    from the column. `id` and `seq` are deliberately left out: both are metadata,
    not the record of what happened. Reordering entries is still caught, because
    the verifier walks in `seq` order and a changed order makes an entry's stored
    `prev_hash` disagree with the one the walk now arrives from; what excluding
    `seq` leaves undetected is renumbering it without changing the order, which
    changes nothing the trail attests to. `id` is a random handle the verifier
    reports a break against, not part of the action it records. Neither is
    available before the row is flushed, either, where the hash is built.
    """
    payload = {
        "prev_hash": prev_hash,
        "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
        "impersonator_user_id": (
            str(impersonator_user_id) if impersonator_user_id is not None else None
        ),
        "organization_id": str(organization_id) if organization_id is not None else None,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "details": details,
        "ip_address": ip_address,
        "created_at": created_at.astimezone(UTC).isoformat(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def record_audit(
    db: AsyncSession,
    *,
    actor_user_id: UUID | None,
    action: str,
    organization_id: UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Persist an audit log entry within the caller's transaction.

    The write shares the request's session, so it commits or rolls back with the
    action it records: a failure to record propagates and rolls the mutation back
    rather than letting a privileged action land unaudited. The trail is
    load-bearing for the app-admin bypass story in `docs/governance.md`, so
    fail-open here would be a hole, not resilience. Swallowing the error also
    never achieved silence - `flush` leaves the session needing a rollback, so
    the request's commit raised `PendingRollbackError` and 500'd anyway.

    `actor_user_id` is `None` for the one caller that has no actor: the approval
    expiry sweep, which records that *nobody* decided. It is required rather than
    defaulted, so passing no actor stays a deliberate act at each call site
    instead of the thing that happens when an argument is forgotten.

    The entry joins a per-organization tamper-evidence chain: it is appended under
    a lock on the organization's chain, links to the previous entry's hash, and
    carries its own (#1622). Serializing per organization is what stops two
    audited writes racing for the same head and forking it; the lock is held to
    the end of the request's transaction, so entries a single transaction records
    chain in the order they were written.

    That lock is transaction-scoped, so a caller must take it *after* the row locks
    of the mutation it records - which a single request does naturally, auditing at
    its end. A batch that audits several entries in one transaction must therefore
    do all its row work first and audit last (see `ApprovalService.expire_stale`):
    holding this chain lock while going on to lock another row lets a concurrent
    decision that holds that row and reaches for the same chain lock close an ABBA
    cycle Postgres has to abort.
    """
    impersonator_id = _impersonator_id.get()
    impersonator = impersonator_id if impersonator_id != actor_user_id else None
    # Before reading the head, not after: a lock taken afterwards serializes
    # nothing, because the head both writers read is already the same stale one.
    await hold_subject(db, LockScope.AUDIT_CHAIN_PER_ORG, organization_id or _DEPLOYMENT_CHAIN)
    head = await db.execute(
        select(AppAdminAuditLog.entry_hash)
        .where(AppAdminAuditLog.organization_id == organization_id)
        .order_by(AppAdminAuditLog.seq.desc())
        .limit(1)
    )
    prev_hash = head.scalar_one_or_none()
    normalized_target_id = str(target_id) if target_id is not None else None
    # Set here rather than left to the column default: the hash covers `created_at`,
    # and the default is applied by the database at flush, after the hash is built.
    created_at = datetime.now(UTC)
    entry = AppAdminAuditLog(
        actor_user_id=actor_user_id,
        impersonator_user_id=impersonator,
        action=action,
        organization_id=organization_id,
        target_type=target_type,
        target_id=normalized_target_id,
        details=details,
        ip_address=ip_address,
        created_at=created_at,
        prev_hash=prev_hash,
        entry_hash=chain_hash(
            prev_hash=prev_hash,
            actor_user_id=actor_user_id,
            impersonator_user_id=impersonator,
            organization_id=organization_id,
            action=action,
            target_type=target_type,
            target_id=normalized_target_id,
            details=details,
            ip_address=ip_address,
            created_at=created_at,
        ),
    )
    db.add(entry)
    await db.flush()
