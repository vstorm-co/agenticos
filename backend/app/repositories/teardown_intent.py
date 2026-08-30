"""What a purge released and has not finished releasing (#1269)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.teardown_intent import TeardownIntent


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    storage_paths: list[str],
    collections: list[str],
) -> TeardownIntent:
    """Record what this purge is about to release.

    Called inside the request's own transaction, so the intent and the delete
    commit together: either both happened or neither did, and there is never a
    committed delete with nothing naming what it left behind.
    """
    intent = TeardownIntent(
        organization_id=organization_id,
        storage_paths=storage_paths,
        collections=collections,
    )
    db.add(intent)
    await db.flush()
    await db.refresh(intent)
    return intent


async def get(db: AsyncSession, intent_id: UUID) -> TeardownIntent | None:
    result = await db.execute(select(TeardownIntent).where(TeardownIntent.id == intent_id))
    return result.scalar_one_or_none()


async def finish(db: AsyncSession, intent_id: UUID) -> None:
    """Delete the intent, which is how the work is recorded as done.

    The row's absence is the completion, so nothing has to interpret a status
    column and no sweep has to decide whether `done` means done.
    """
    intent = await get(db, intent_id)
    if intent is not None:
        await db.delete(intent)
        await db.flush()


async def claim_stale(
    db: AsyncSession, *, older_than: timedelta, limit: int
) -> list[TeardownIntent]:
    """Intents nothing has finished, oldest first, locked for this sweep.

    Two shapes qualify: never dispatched, which is a crash between the commit
    and the hand-off; and dispatched long enough ago that the run it named is
    not coming back. `skip_locked` so two workers sweeping at once take
    different rows rather than one waiting on the other.

    Stamping `dispatched_at` is the claim. A row is re-dispatched rather than
    given up on, because the flow itself is idempotent - unlinking a file
    already gone is a no-op, and each collection is re-checked before it is
    dropped - so the cost of dispatching twice is a wasted run and the cost of
    not dispatching is an orphan nobody can find.
    """
    cutoff = datetime.now(UTC) - older_than
    result = await db.execute(
        select(TeardownIntent)
        .where(
            or_(
                TeardownIntent.dispatched_at.is_(None),
                TeardownIntent.dispatched_at < cutoff,
            )
        )
        .order_by(TeardownIntent.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    claimed = list(result.scalars())
    now = datetime.now(UTC)
    for intent in claimed:
        intent.dispatched_at = now
        intent.attempts += 1
    await db.flush()
    return claimed


async def mark_dispatched(db: AsyncSession, intent_id: UUID) -> None:
    """Stamp the hand-off that happens straight after the purge commits."""
    intent = await get(db, intent_id)
    if intent is not None:
        intent.dispatched_at = datetime.now(UTC)
        intent.attempts += 1
        await db.flush()
