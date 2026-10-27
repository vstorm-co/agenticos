"""Sync log repository (PostgreSQL async).

Contains database operations for SyncLog entities.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sync_log import SyncLog


async def get_by_id(db: AsyncSession, sync_id: UUID) -> SyncLog | None:
    """Get a sync log by ID."""
    return await db.get(SyncLog, sync_id)


@dataclass(frozen=True)
class SyncLogScope:
    """The sync runs a listing may include.

    A run carries a collection name and, when a sync source started it, that
    source - no organization and no base. The name alone is not whose a run is:
    an app-scoped base and an organization's base can share it, and every
    member of every organization reads the app base. So a run started by a
    source is listed only when that source is one of `sync_source_ids` - the
    sources feeding a base the caller reads - and a run with no source (a local
    directory or command-line sync, or one whose source was deleted) by its name.
    """

    collections: list[str]
    sync_source_ids: list[UUID]


async def get_all(
    db: AsyncSession,
    scope: SyncLogScope | None = None,
    sync_source_id: UUID | None = None,
    limit: int = 20,
) -> list[SyncLog]:
    """Get sync logs, optionally filtered by a scope or one sync source.

    An empty `scope` means "nothing is in scope", and answers with nothing
    rather than with everything.
    """
    query = select(SyncLog)
    if scope is not None:
        query = query.where(
            SyncLog.collection_name.in_(scope.collections),
            or_(
                SyncLog.sync_source_id.is_(None),
                SyncLog.sync_source_id.in_(scope.sync_source_ids),
            ),
        )
    if sync_source_id:
        query = query.where(SyncLog.sync_source_id == sync_source_id)
    query = query.order_by(SyncLog.started_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    source: str,
    collection_name: str,
    mode: str,
    status: str = "running",
    sync_source_id: UUID | None = None,
    triggered_by_user_id: UUID | None = None,
) -> SyncLog:
    """Create a new sync log record."""
    log = SyncLog(
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
