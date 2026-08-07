"""Audit log helpers for recording privileged actions."""

import logging
from typing import Any
from uuid import UUID

from app.db.models.audit_log import AppAdminAuditLog

logger = logging.getLogger(__name__)


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
        entry = AppAdminAuditLog(
            actor_user_id=actor_user_id,
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
