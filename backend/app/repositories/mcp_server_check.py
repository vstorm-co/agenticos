"""Reading and writing what the catalog check found per MCP listing."""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mcp_server_check import McpServerCheck


async def get_many(db: AsyncSession, keys: Collection[str]) -> dict[str, McpServerCheck]:
    """The checks held for these listings, by key; a listing never checked is absent."""
    if not keys:
        return {}
    result = await db.execute(select(McpServerCheck).where(McpServerCheck.key.in_(keys)))
    return {check.key: check for check in result.scalars().all()}


async def count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(McpServerCheck)) or 0


async def upsert_many(db: AsyncSession, rows: Sequence[dict[str, Any]]) -> int:
    """Write these checks, replacing an earlier one for the same listing.

    A check is a fact about the most recent call, so the newer one wins outright
    rather than merging with what an older run saw.
    """
    if not rows:
        return 0
    statement = insert(McpServerCheck).values(list(rows))
    statement = statement.on_conflict_do_update(
        index_elements=[McpServerCheck.key],
        set_={
            "source": statement.excluded.source,
            "outcome": statement.excluded.outcome,
            "auth": statement.excluded.auth,
            "tools": statement.excluded.tools,
            "read_only_tools": statement.excluded.read_only_tools,
            "duplicate_of": statement.excluded.duplicate_of,
            "checked_at": statement.excluded.checked_at,
            "updated_at": func.now(),
        },
    )
    await db.execute(statement)
    await db.flush()
    return len(rows)


async def insert_missing(db: AsyncSession, rows: Sequence[dict[str, Any]]) -> int:
    """Write the checks for listings that have none, leaving every existing one.

    How the bundled snapshot is seeded: a deployment that ran its own check knows
    more recent things than the snapshot a release shipped with.
    """
    if not rows:
        return 0
    statement = insert(McpServerCheck).values(list(rows)).on_conflict_do_nothing()
    result = cast(CursorResult[Any], await db.execute(statement))
    await db.flush()
    return result.rowcount or 0


async def delete_stale(db: AsyncSession, before: datetime) -> int:
    """Drop checks a full run did not write - listings that are no longer listed."""
    result = cast(
        CursorResult[Any],
        await db.execute(delete(McpServerCheck).where(McpServerCheck.checked_at < before)),
    )
    await db.flush()
    return result.rowcount or 0
