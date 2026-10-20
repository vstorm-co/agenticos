"""Data access for remote sandboxes still to be destroyed (#2209)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pending_sandbox_destroy import PendingSandboxDestroy


async def add(
    db: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID,
    ref_id: str,
    scope_key: str,
) -> PendingSandboxDestroy:
    """Record a sandbox to destroy, in the transaction that deletes its rows."""
    row = PendingSandboxDestroy(
        organization_id=organization_id,
        connection_id=connection_id,
        ref_id=ref_id,
        scope_key=scope_key,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def remove(db: AsyncSession, pending_id: UUID) -> None:
    """Forget a sandbox the provider has confirmed destroyed. A row already gone is fine."""
    await db.execute(delete(PendingSandboxDestroy).where(PendingSandboxDestroy.id == pending_id))
    await db.flush()


async def claim_due(
    db: AsyncSession, *, now: datetime, limit: int
) -> Sequence[PendingSandboxDestroy]:
    """The tombstones whose next attempt is due, oldest first, locked for this sweep.

    `SKIP LOCKED`, so two workers sweeping at once each take different rows
    rather than destroying the same sandbox twice.
    """
    result = await db.execute(
        select(PendingSandboxDestroy)
        .where(PendingSandboxDestroy.next_attempt_at <= now)
        .order_by(PendingSandboxDestroy.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return result.scalars().all()


async def postpone(db: AsyncSession, pending_id: UUID, *, attempts: int, until: datetime) -> None:
    """Record a failed attempt and when to try again."""
    await db.execute(
        update(PendingSandboxDestroy)
        .where(PendingSandboxDestroy.id == pending_id)
        .values(attempts=attempts, next_attempt_at=until)
    )
    await db.flush()


async def count_on_connection(db: AsyncSession, *, connection_id: UUID) -> int:
    """How many sandboxes on a connection are still to be destroyed."""
    result = await db.execute(
        select(func.count())
        .select_from(PendingSandboxDestroy)
        .where(PendingSandboxDestroy.connection_id == connection_id)
    )
    return result.scalar_one()
