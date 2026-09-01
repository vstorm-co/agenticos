"""Data access for collection-teardown tombstones (#1362)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.collection_teardown import CollectionTeardown


async def reserve(db: AsyncSession, collection_name: str) -> None:
    """Reserve a name while its vector table is torn down.

    Idempotent: a name already reserved (a retried teardown, or one collection
    reached by two paths in a purge) conflicts on the primary key and is left as it
    was, rather than raising.
    """
    stmt = insert(CollectionTeardown).values(collection_name=collection_name)
    await db.execute(stmt.on_conflict_do_nothing(index_elements=["collection_name"]))
    await db.flush()


async def is_reserved(db: AsyncSession, collection_name: str) -> bool:
    """Whether a name is mid-teardown, so a claim must not adopt its lingering table."""
    result = await db.execute(
        select(CollectionTeardown.collection_name).where(
            CollectionTeardown.collection_name == collection_name
        )
    )
    return result.scalar_one_or_none() is not None


async def release(db: AsyncSession, collection_name: str) -> None:
    """Free a name once its table is gone.

    Idempotent: a name that carried no tombstone - a default base kept its row and
    blocked reuse without one - releases to a no-op.
    """
    row = await db.get(CollectionTeardown, collection_name)
    if row is not None:
        await db.delete(row)
        await db.flush()
