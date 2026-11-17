"""Tenant-scoped browser teaching persistence. Every read names the organization."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.browser_teaching import BrowserTeachingSession

_ACTIVE = ("recording", "paused")
_OPEN = ("recording", "paused", "review")


async def get(
    db: AsyncSession, organization_id: UUID, session_id: UUID, *, locked: bool = False
) -> BrowserTeachingSession | None:
    statement = select(BrowserTeachingSession).where(
        BrowserTeachingSession.organization_id == organization_id,
        BrowserTeachingSession.id == session_id,
    )
    if locked:
        statement = statement.with_for_update()
    return await db.scalar(statement.execution_options(populate_existing=True))


async def by_request(
    db: AsyncSession, organization_id: UUID, owner_user_id: UUID, request_key: str
) -> BrowserTeachingSession | None:
    return await db.scalar(
        select(BrowserTeachingSession).where(
            BrowserTeachingSession.organization_id == organization_id,
            BrowserTeachingSession.owner_user_id == owner_user_id,
            BrowserTeachingSession.request_key == request_key,
        )
    )


async def active_for_view(
    db: AsyncSession, organization_id: UUID, run_id: UUID, call_id: str, *, locked: bool = False
) -> BrowserTeachingSession | None:
    statement = select(BrowserTeachingSession).where(
        BrowserTeachingSession.organization_id == organization_id,
        BrowserTeachingSession.run_id == run_id,
        BrowserTeachingSession.call_id == call_id,
        BrowserTeachingSession.status.in_(_ACTIVE),
    )
    if locked:
        statement = statement.with_for_update()
    return await db.scalar(statement.execution_options(populate_existing=True))


async def create(db: AsyncSession, row: BrowserTeachingSession) -> BrowserTeachingSession:
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def sweep_candidates(
    db: AsyncSession, now: datetime, *, limit: int = 200
) -> list[tuple[UUID, UUID]]:
    """Open rows past retention, plus active rows whose lease or time must be rechecked."""
    rows = await db.execute(
        select(BrowserTeachingSession.organization_id, BrowserTeachingSession.id)
        .where(
            or_(
                BrowserTeachingSession.status.in_(_ACTIVE),
                (BrowserTeachingSession.status.in_(_OPEN))
                & (BrowserTeachingSession.expires_at <= now),
            )
        )
        .order_by(BrowserTeachingSession.updated_at.asc().nulls_first())
        .limit(limit)
    )
    return [(organization_id, session_id) for organization_id, session_id in rows.all()]
