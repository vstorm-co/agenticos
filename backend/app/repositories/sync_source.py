"""Sync source repository (PostgreSQL async).

Contains database operations for SyncSource entities.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sync_source import SyncSource


async def get_by_id(db: AsyncSession, source_id: UUID) -> SyncSource | None:
    """Get a sync source by ID."""
    return await db.get(SyncSource, source_id)


async def get_all(
    db: AsyncSession,
    *,
    organization_id: UUID | None = None,
    collection_name: str | None = None,
    is_active: bool | None = None,
) -> list[SyncSource]:
    """List sync sources with optional org, collection, and active filters."""
    query = select(SyncSource)
    if organization_id is not None:
        query = query.where(SyncSource.organization_id == organization_id)
    if collection_name is not None:
        query = query.where(SyncSource.collection_name == collection_name)
    if is_active is not None:
        query = query.where(SyncSource.is_active == is_active)
    query = query.order_by(SyncSource.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def list_for_collections(db: AsyncSession, collection_names: list[str]) -> list[SyncSource]:
    """Every organization's sync sources writing into any of these collections.

    Unfiltered by organization on purpose: the caller decides which of them
    feed a base it may read (`CollectionAccessService`), by the base each
    source's sync resolves to.
    """
    if not collection_names:
        return []
    result = await db.execute(
        select(SyncSource).where(SyncSource.collection_name.in_(collection_names))
    )
    return list(result.scalars().all())


async def get_due_for_sync(db: AsyncSession) -> list[SyncSource]:
    """Active scheduled sources that are due for sync."""
    now = datetime.now(UTC)
    query = select(SyncSource).where(
        SyncSource.is_active == True,  # noqa: E712
        SyncSource.schedule_minutes.isnot(None),
        SyncSource.collection_name.isnot(None),
    )
    result = await db.execute(query)
    sources = list(result.scalars().all())
    return [
        s
        for s in sources
        if s.schedule_minutes is not None
        and (
            s.last_sync_at is None or s.last_sync_at + timedelta(minutes=s.schedule_minutes) <= now
        )
    ]


async def any_due_for_sync(db: AsyncSession) -> bool:
    """Whether `get_due_for_sync` would find anything - one `EXISTS`, no row loaded.

    The worker asks this every minute in its own process (`dispatch_due_syncs`),
    where loading every scheduled source with its configuration to answer a
    yes-or-no question would put each tenant's sources in that process's memory.
    """
    due = or_(
        SyncSource.last_sync_at.is_(None),
        SyncSource.last_sync_at
        + literal_column("interval '1 minute'") * SyncSource.schedule_minutes
        <= func.now(),
    )
    query = select(
        select(SyncSource.id)
        .where(
            SyncSource.is_active == True,  # noqa: E712
            SyncSource.schedule_minutes.isnot(None),
            SyncSource.collection_name.isnot(None),
            due,
        )
        .exists()
    )
    return bool(await db.scalar(query))


async def create(
    db: AsyncSession,
    *,
    name: str,
    connector_type: str,
    config: dict[str, object],
    organization_id: UUID,
    collection_name: str | None = None,
    secret_id: UUID | None = None,
    organizational_unit: str | None = None,
    sync_mode: str = "new_only",
    schedule_minutes: int | None = None,
) -> SyncSource:
    """Create a new sync source configuration."""
    source = SyncSource(
        name=name,
        connector_type=connector_type,
        organization_id=organization_id,
        collection_name=collection_name,
        config=config,
        secret_id=secret_id,
        organizational_unit=organizational_unit,
        sync_mode=sync_mode,
        schedule_minutes=schedule_minutes,
    )
    db.add(source)
    await db.flush()
    return source


async def update(
    db: AsyncSession,
    source_id: UUID,
    **updates: object,
) -> SyncSource | None:
    """Update a sync source with the given fields.

    A key that is present is written, `None` included. "Not provided" is a key
    that is absent, which is what `app/db/updates.py` already decided before
    calling: it keeps an explicit `None` for a nullable column and drops one a
    `NOT NULL` column would refuse.

    This used to skip every `None`, which made a nullable column unclearable -
    `{"secret_id": null}` answered 200 and left the old credential attached, so a
    source could not be detached from a vault secret through the API at all
    (#937).
    """
    source = await db.get(SyncSource, source_id)
    if not source:
        return None
    for key, value in updates.items():
        if hasattr(source, key):
            setattr(source, key, value)
    await db.flush()
    return source


async def delete(db: AsyncSession, source_id: UUID) -> bool:
    """Delete a sync source by ID. Returns True if deleted."""
    source = await db.get(SyncSource, source_id)
    if not source:
        return False
    await db.delete(source)
    await db.flush()
    return True


async def update_sync_status(
    db: AsyncSession,
    source_id: UUID,
    *,
    last_sync_at: datetime,
    last_sync_status: str,
    last_error: str | None = None,
    sync_state: dict[str, str] | None = None,
) -> SyncSource | None:
    """Update the sync status fields after a sync operation.

    `sync_state` is written when given and kept when not: only a clean run
    records one, and a failed run must leave the last clean one in place.
    """
    source = await db.get(SyncSource, source_id)
    if not source:
        return None
    source.last_sync_at = last_sync_at
    source.last_sync_status = last_sync_status
    source.last_error = last_error
    if sync_state is not None:
        source.sync_state = sync_state
    await db.flush()
    return source
