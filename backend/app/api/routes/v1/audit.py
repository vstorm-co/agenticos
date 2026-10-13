"""Audit routes - who did what in this organization.

Gated by `audit:read`, which owners and admins hold. The log is written by the
services performing gated mutations, not by the route layer, so an action is
recorded whether it arrives over HTTP, a channel or a background flow.
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuditSvc, Auth, require
from app.api.responses import csv_response, jsonl_response
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


@router.get(
    "/audit/export",
    response_model=None,
    dependencies=[Depends(require(Perm.AUDIT_READ))],
)
async def export_audit_entries(
    service: AuditSvc,
    ctx: Auth,
    created_from: datetime | None = Query(None, description="Window start, inclusive. Required"),
    created_to: datetime | None = Query(None, description="Window end, inclusive. Required"),
    fmt: Literal["csv", "jsonl"] = Query(
        "csv", description="csv for a spreadsheet, jsonl for a pipeline"
    ),
) -> Any:
    """The organization's audit trail over a window, as CSV or JSONL.

    The same `audit:read` gate and organization scope as the list. Two differences
    an export demands: the date range is **mandatory** (a refusal names the missing
    bound), and a match over the row cap is **refused** rather than paged. The
    export is itself audited.
    """
    result = await service.export(ctx, since=created_from, until=created_to, fmt=fmt)
    return jsonl_response(result) if fmt == "jsonl" else csv_response(result)
