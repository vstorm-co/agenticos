"""Audit log repository (PostgreSQL async)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AppAdminAuditLog


async def list_for_org(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skip: int = 0,
    limit: int = 50,
) -> list[AppAdminAuditLog]:
    """One organization's audit entries, newest first."""
    result = await db.execute(
        select(AppAdminAuditLog)
        .where(AppAdminAuditLog.organization_id == organization_id)
        .order_by(AppAdminAuditLog.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_for_org(db: AsyncSession, *, organization_id: UUID) -> int:
    result = await db.scalar(
        select(func.count())
        .select_from(AppAdminAuditLog)
        .where(AppAdminAuditLog.organization_id == organization_id)
    )
    return result or 0


async def list_in_window_for_org(
    db: AsyncSession,
    *,
    organization_id: UUID,
    since: datetime,
    until: datetime,
    limit: int,
) -> tuple[list[AppAdminAuditLog], int]:
    """One organization's entries in a half-open date window, newest first, and the
    total in that window.

    The total is a separate count, not `len(items)`: the caller caps the fetch at
    `limit` and refuses above the count, so it has to know the whole match before
    reading a bounded slice of it. Both narrow to the same window and organization.
    """
    where = (
        AppAdminAuditLog.organization_id == organization_id,
        AppAdminAuditLog.created_at >= since,
        AppAdminAuditLog.created_at <= until,
    )
    total = await db.scalar(select(func.count()).select_from(AppAdminAuditLog).where(*where))
    result = await db.execute(
        select(AppAdminAuditLog)
        .where(*where)
        .order_by(AppAdminAuditLog.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all()), total or 0
