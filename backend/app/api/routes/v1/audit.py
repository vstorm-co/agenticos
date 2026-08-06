"""Audit routes - who did what in this organization.

Gated by `audit:read`, which owners and admins hold. The log is written by the
services performing gated mutations, not by the route layer, so an action is
recorded whether it arrives over HTTP, a channel or a background flow.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuditSvc, Auth, require
from app.core.permissions import Perm
from app.schemas.audit import AuditEntryList

router = APIRouter()


@router.get(
    "/audit",
    response_model=AuditEntryList,
    dependencies=[Depends(require(Perm.AUDIT_READ))],
)
async def list_audit_entries(
    service: AuditSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max items to return"),
) -> Any:
    """Audit entries for the active organization, newest first."""
    return await service.list_for_organization(ctx, skip=skip, limit=limit)
