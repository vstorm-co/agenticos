"""Sync log repository (PostgreSQL async).

Contains database operations for SyncLog entities.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, false, func, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sync_log import SyncLog
from app.db.models.sync_source import SyncSource


async def get_by_id(db: AsyncSession, sync_id: UUID) -> SyncLog | None:
    """Get a sync log by ID."""
    return await db.get(SyncLog, sync_id)


async def detach_sources_from_base_history(db: AsyncSession, knowledge_base_id: UUID) -> None:
    """Archive source provenance before deletion clears the recorded base FK.

    A NULL-base log can be legacy history attributed through its source. Once
    its recorded base is deleted it must not inherit a repointed source's audience.
    The caller holds the base lock until deletion and commit.
    """
    await db.execute(
        update(SyncLog)
        .where(SyncLog.knowledge_base_id == knowledge_base_id)
        .values(sync_source_id=None)
    )
    await db.flush()


@dataclass(frozen=True)
class SyncLogScope:
    """The sync runs a listing may include.

    A source-backed legacy run is readable through its authorized source. New
    runs retain organization and base ownership after that source is deleted.
    A source-less legacy run with unknown ownership is never inferred from a
    shared collection name.
    """

    collections: list[str]
    sync_source_ids: list[UUID]
    organization_id: UUID | None = None
    knowledge_base_ids: tuple[UUID, ...] = ()
    all_organizations: bool = False


def _scoped_query(scope: SyncLogScope | None, sync_source_id: UUID | None) -> Select[SyncLog]:
    query = select(SyncLog)
    if scope is not None:
        tenant = true() if scope.all_organizations else false()
        if not scope.all_organizations and scope.organization_id is not None:
            tenant = or_(
                SyncLog.organization_id == scope.organization_id,
                and_(
                    SyncLog.organization_id.is_(None),
                    SyncLog.sync_source_id.in_(
                        select(SyncSource.id).where(
                            SyncSource.organization_id == scope.organization_id
                        )
                    ),
                ),
            )
        query = query.where(
            SyncLog.collection_name.in_(scope.collections),
            or_(
                and_(SyncLog.knowledge_base_id.in_(scope.knowledge_base_ids), tenant),
                and_(
                    SyncLog.knowledge_base_id.is_(None),
                    SyncLog.sync_source_id.in_(scope.sync_source_ids),
                ),
            ),
        )
    if sync_source_id:
        query = query.where(SyncLog.sync_source_id == sync_source_id)
    return query


async def get_all(
    db: AsyncSession,
    scope: SyncLogScope | None = None,
    sync_source_id: UUID | None = None,
    limit: int = 20,
    skip: int = 0,
) -> list[SyncLog]:
    """Page authorized logs with deterministic ordering, filtering before pagination."""
    query = (
        _scoped_query(scope, sync_source_id)
        .order_by(SyncLog.started_at.desc(), SyncLog.id.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_all(db: AsyncSession, *, scope: SyncLogScope, sync_source_id: UUID) -> int:
    """Count the same immutable authorized history that a page reads."""
    return (
        await db.scalar(
            select(func.count()).select_from(_scoped_query(scope, sync_source_id).subquery())
        )
        or 0
    )


async def create(
    db: AsyncSession,
    *,
    source: str,
    collection_name: str,
    mode: str,
    status: str = "running",
    sync_source_id: UUID | None = None,
    triggered_by_user_id: UUID | None = None,
    organization_id: UUID | None = None,
    knowledge_base_id: UUID | None = None,
) -> SyncLog:
    """Create a new sync log record."""
    log = SyncLog(
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        source=source,
        collection_name=collection_name,
        mode=mode,
        status=status,
        sync_source_id=sync_source_id,
        triggered_by_user_id=triggered_by_user_id,
    )
    db.add(log)
    await db.flush()
    return log


async def update_status(
    db: AsyncSession,
    sync_id: UUID,
    *,
    status: str,
    total_files: int | None = None,
    ingested: int | None = None,
    updated: int | None = None,
    skipped: int | None = None,
    failed: int | None = None,
    removed: int | None = None,
    error_message: str | None = None,
    completed_at: Any = None,
) -> SyncLog | None:
    """Update the status and counters of a sync log."""
    log = await db.get(SyncLog, sync_id)
    if not log:
        return None
    log.status = status
    if total_files is not None:
        log.total_files = total_files
    if ingested is not None:
        log.ingested = ingested
    if updated is not None:
        log.updated = updated
    if skipped is not None:
        log.skipped = skipped
    if failed is not None:
        log.failed = failed
    if removed is not None:
        log.removed = removed
    if error_message is not None:
        log.error_message = error_message
    if completed_at is not None:
        log.completed_at = completed_at
    await db.flush()
    return log
