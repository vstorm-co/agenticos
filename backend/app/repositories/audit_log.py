"""Audit log repository (PostgreSQL async)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_checkpoint import AppAdminAuditCheckpoint
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
    """One organization's entries in a closed date window, newest first, and the
    total in that window.

    The total is `count(*) OVER()` on the same statement as the rows, not a
    separate query: the caller caps the fetch at `limit` and refuses above the
    total, and two statements under READ COMMITTED could see different snapshots -
    a count of 10,000 then a select over 10,001 - so the export would truncate to
    the cap where it promised to refuse. A window function is evaluated before the
    LIMIT, so the total is the whole match and the rows are its first `limit`, from
    one snapshot.
    """
    where = (
        AppAdminAuditLog.organization_id == organization_id,
        AppAdminAuditLog.created_at >= since,
        AppAdminAuditLog.created_at <= until,
    )
    result = await db.execute(
        select(AppAdminAuditLog, func.count().over().label("total"))
        .where(*where)
        .order_by(AppAdminAuditLog.created_at.desc())
        .limit(limit)
    )
    rows = result.all()
    total = rows[0].total if rows else 0
    return [row[0] for row in rows], total


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


async def checkpoint_for_org(
    db: AsyncSession, *, organization_id: UUID | None
) -> AppAdminAuditCheckpoint | None:
    """This chain's high-water mark, or None if it has never been checkpointed.
    `None` reads the deployment-wide chain's checkpoint."""
    condition = (
        AppAdminAuditCheckpoint.organization_id.is_(None)
        if organization_id is None
        else AppAdminAuditCheckpoint.organization_id == organization_id
    )
    result = await db.execute(select(AppAdminAuditCheckpoint).where(condition))
    return result.scalar_one_or_none()


async def distinct_checkpoint_organization_ids(db: AsyncSession) -> list[UUID | None]:
    """Every organization that has a checkpoint - the set `audit-verify` adds so a
    chain deleted whole (no entries left, but a checkpoint remaining) is still
    walked."""
    result = await db.execute(select(AppAdminAuditCheckpoint.organization_id).distinct())
    return list(result.scalars().all())
