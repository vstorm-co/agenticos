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


async def distinct_organization_ids(db: AsyncSession) -> list[UUID | None]:
    """Every chain the log holds - one organization id per chain, and `None` for
    the deployment-wide chain when it has any entries. This is the set
    `audit-verify` walks when no organization is named."""
    result = await db.execute(select(AppAdminAuditLog.organization_id).distinct())
    return list(result.scalars().all())


async def chain_for_org(
    db: AsyncSession, *, organization_id: UUID | None
) -> list[AppAdminAuditLog]:
    """One chain's entries in the order they link - `seq` ascending. `None` reads
    the deployment-wide chain, whose entries carry no organization."""
    condition = (
        AppAdminAuditLog.organization_id.is_(None)
        if organization_id is None
        else AppAdminAuditLog.organization_id == organization_id
    )
    result = await db.execute(
        select(AppAdminAuditLog).where(condition).order_by(AppAdminAuditLog.seq.asc())
    )
    return list(result.scalars().all())
