"""Audit routes - who did what in this organization.

Gated by `audit:read`, which owners and admins hold. The log is written by the
services performing gated mutations, not by the route layer, so an action is
recorded whether it arrives over HTTP, a channel or a background flow.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import Auth, DBSession, require
from app.core.permissions import Perm
from app.repositories import audit_log_repo
from app.schemas.audit import AuditEntryList, AuditEntryRead

router = APIRouter()


@router.get(
    "/audit",
    response_model=AuditEntryList,
    dependencies=[Depends(require(Perm.AUDIT_READ))],
)
async def list_audit_entries(
    db: DBSession,
    ctx: Auth,
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
) -> Any:
    """Audit entries for the active organization, newest first."""
    items = await audit_log_repo.list_for_org(
        db, organization_id=ctx.organization_id, skip=skip, limit=limit
    )
    total = await audit_log_repo.count_for_org(db, organization_id=ctx.organization_id)
    return AuditEntryList(
        items=[
            AuditEntryRead(
                id=entry.id,
                actor_user_id=entry.actor_user_id,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                details=entry.details,
                created_at=entry.created_at,
            )
            for entry in items
        ],
        total=total,
    )
