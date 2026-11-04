"""What people asked the platform to watch in their connections (#2301)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.watch import Watch


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    connection_id: UUID,
    preset_key: str | None,
    title: str,
    instructions: str,
    urgent: bool,
    interval_minutes: int,
    next_run_at: datetime,
) -> Watch:
    watch = Watch(
        organization_id=organization_id,
        user_id=user_id,
        connection_id=connection_id,
        preset_key=preset_key,
        title=title,
        instructions=instructions,
        exclusions=[],
        urgent=urgent,
        interval_minutes=interval_minutes,
        is_active=True,
        next_run_at=next_run_at,
    )
    db.add(watch)
    await db.flush()
    await db.refresh(watch)
    return watch


async def list_own(db: AsyncSession, *, organization_id: UUID, user_id: UUID) -> list[Watch]:
    """One person's watches here, oldest first - the order they were set up in."""
    result = await db.execute(
        select(Watch)
        .where(Watch.organization_id == organization_id, Watch.user_id == user_id)
        .order_by(Watch.created_at, Watch.id)
    )
    return list(result.scalars().all())


async def get_own(
    db: AsyncSession, watch_id: UUID, *, organization_id: UUID, user_id: UUID
) -> Watch | None:
    result = await db.execute(
        select(Watch).where(
            Watch.id == watch_id,
            Watch.organization_id == organization_id,
            Watch.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, watch_id: UUID) -> Watch | None:
    return await db.get(Watch, watch_id)


async def update_fields(db: AsyncSession, *, watch: Watch, changes: dict[str, Any]) -> Watch:
    for field, value in changes.items():
        setattr(watch, field, value)
    await db.flush()
    await db.refresh(watch)
    return watch


async def delete(db: AsyncSession, watch: Watch) -> None:
    await db.delete(watch)
    await db.flush()


async def claim_due(db: AsyncSession, *, now: datetime, limit: int) -> list[Watch]:
    """Active watches whose time has come, locked so two sweeps never take the same one."""
    result = await db.execute(
        select(Watch)
        .where(Watch.is_active.is_(True), Watch.next_run_at <= now)
        .order_by(Watch.next_run_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def schedule(db: AsyncSession, *, watch_id: UUID, next_run_at: datetime) -> None:
    """Move one watch's next look, without loading it."""
    await db.execute(update(Watch).where(Watch.id == watch_id).values(next_run_at=next_run_at))


async def mark_ran(db: AsyncSession, *, watch: Watch, at: datetime) -> None:
    watch.last_run_at = at
    await db.flush()
