"""Audit log helpers for recording privileged actions."""

import logging
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from app.db.models.audit_log import AppAdminAuditLog

logger = logging.getLogger(__name__)

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


async def record_audit(
    db,
    *,
    actor_user_id: UUID | None,
    action: str,
    organization_id: UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Persist an audit log entry. Failures are logged but do not raise.

    `actor_user_id` is `None` for the one caller that has no actor: the approval
    expiry sweep, which records that *nobody* decided. It is required rather than
    defaulted, so passing no actor stays a deliberate act at each call site
    instead of the thing that happens when an argument is forgotten.
    """
    try:
        impersonator_id = _impersonator_id.get()
        entry = AppAdminAuditLog(
            actor_user_id=actor_user_id,
            impersonator_user_id=impersonator_id if impersonator_id != actor_user_id else None,
            action=action,
            organization_id=organization_id,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details,
            ip_address=ip_address,
        )
        db.add(entry)
        await db.flush()
    except Exception:
        logger.exception("Failed to write audit log for action=%s actor=%s", action, actor_user_id)
