"""Data access for the worker processes that run background jobs (#2219)."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_worker import BackgroundWorker


async def beat(db: AsyncSession, *, worker_id: str, hostname: str, pools: Sequence[str]) -> None:
    """Say this worker is alive, registering it on its first beat."""
    statement = insert(BackgroundWorker).values(id=worker_id, hostname=hostname, pools=list(pools))
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[BackgroundWorker.id], set_={"heartbeat_at": func.now()}
        )
    )


async def remove(db: AsyncSession, worker_id: str) -> None:
    """Forget a worker that stopped cleanly."""
    await db.execute(delete(BackgroundWorker).where(BackgroundWorker.id == worker_id))


async def list_seen_since(db: AsyncSession, *, since: datetime) -> Sequence[BackgroundWorker]:
    """The workers that beat at or after `since`, longest-running first."""
    result = await db.execute(
        select(BackgroundWorker)
        .where(BackgroundWorker.heartbeat_at >= since)
        .order_by(BackgroundWorker.started_at)
    )
    return result.scalars().all()


async def forget_silent_since(db: AsyncSession, *, before: datetime) -> int:
    """Remove the workers that have not beaten since `before`. Answers how many."""
    rows = await db.execute(
        delete(BackgroundWorker)
        .where(BackgroundWorker.heartbeat_at < before)
        .returning(BackgroundWorker.id)
    )
    return len(rows.all())
