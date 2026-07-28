"""Audit log repository (PostgreSQL async)."""

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
