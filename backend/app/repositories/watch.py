"""What people asked the platform to watch in their connections (#2301)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.db.models.watch import Watch, WatchAttemptStatus


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
    max_failures: int | None = 3,
    notification_channels: Sequence[str] | None = None,
    report_mode: str = "changes",
    agent_id: UUID | None = None,
    environment_id: UUID | None = None,
    pinned_version_id: UUID | None = None,
    approved_sources: dict[str, object] | None = None,
    source_conversation_id: UUID | None = None,
    ends_at: datetime | None = None,
) -> Watch:
    watch = Watch(
        max_failures=max_failures,
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
        notification_channels=None
        if notification_channels is None
        else list(notification_channels),
        report_mode=report_mode,
        agent_id=agent_id,
        environment_id=environment_id,
        pinned_version_id=pinned_version_id,
        approved_sources=approved_sources,
        source_conversation_id=source_conversation_id,
        ends_at=ends_at,
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
    db: AsyncSession,
    watch_id: UUID,
    *,
    organization_id: UUID,
    user_id: UUID,
    for_update: bool = False,
) -> Watch | None:
    query = select(Watch).where(
        Watch.id == watch_id,
        Watch.organization_id == organization_id,
        Watch.user_id == user_id,
    )
    if for_update:
        # Serialize deletion with the foreign-key lock taken by new findings.
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_by_id(
    db: AsyncSession, watch_id: UUID, *, fresh: bool = False, for_update: bool = False
) -> Watch | None:
    return await db.get(
        Watch, watch_id, populate_existing=fresh or for_update, with_for_update=for_update
    )


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


async def mark_ran(db: AsyncSession, *, watch: Watch, at: datetime) -> bool:
    return await mark_attempt(db, watch=watch, at=at, status=WatchAttemptStatus.COMPLETED)


async def mark_attempt(
    db: AsyncSession, *, watch: Watch, at: datetime, status: WatchAttemptStatus
) -> bool:
    """Retain the newest attempt and successful reading despite out-of-order completion."""
    newest = or_(Watch.last_attempt_at.is_(None), Watch.last_attempt_at <= at)
    values: dict[str, object] = {
        "last_attempt_at": case((newest, at), else_=Watch.last_attempt_at),
        "last_attempt_status": case((newest, status.value), else_=Watch.last_attempt_status),
    }
    if status == WatchAttemptStatus.COMPLETED:
        values["last_run_at"] = case(
            (or_(Watch.last_run_at.is_(None), Watch.last_run_at <= at), at), else_=Watch.last_run_at
        )
    result = await db.execute(
        update(Watch)
        .where(Watch.id == watch.id)
        .execution_options(synchronize_session=False)
        .values(**values)
        .returning(
            Watch.last_attempt_at, Watch.last_attempt_status, Watch.last_run_at, Watch.is_active
        )
    )
    row = result.tuples().one_or_none()
    if row is None:
        return False
    latest_at, latest_status, successful_at, active = row
    # Cache the atomic result without scheduling a later, unconditional ORM write.
    set_committed_value(watch, "last_attempt_at", latest_at)
    set_committed_value(watch, "last_attempt_status", latest_status)
    set_committed_value(watch, "last_run_at", successful_at)
    set_committed_value(watch, "is_active", active)
    return latest_at == at


async def claim_report_activation(
    db: AsyncSession, *, watch_id: UUID, scheduled_for: datetime
) -> bool:
    """Commit the report marker with its result writes; retries cannot replay that activation."""
    result = await db.execute(
        update(Watch)
        .where(
            Watch.id == watch_id,
            (Watch.last_reported_activation.is_(None))
            | (Watch.last_reported_activation < scheduled_for),
        )
        .execution_options(synchronize_session=False)
        .values(last_reported_activation=scheduled_for)
        .returning(Watch.id)
    )
    return result.scalar_one_or_none() is not None


async def claim_ended(db: AsyncSession, *, now: datetime, limit: int) -> list[Watch]:
    """Claim unfinished deadline cleanup independently of activation cadence and pause."""
    result = await db.scalars(
        select(Watch)
        .where(
            Watch.ends_at <= now,
            or_(Watch.is_active.is_(True), Watch.end_settled_at.is_distinct_from(Watch.ends_at)),
        )
        .order_by(Watch.ends_at, Watch.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return list(result.all())
