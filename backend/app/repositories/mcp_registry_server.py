"""Reading and refreshing the mirrored MCP registry."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mcp_registry_server import McpRegistryServer

_BAND_NAME_STARTS = 0
_BAND_NAME_HOLDS = 1
_BAND_ELSEWHERE = 2


def _bands(needle: str) -> Any:
    """The ranking, as SQL, so it survives paging.

    Three bands, and they have to be computed in the database rather than after
    the fact: ranking a page is ranking whatever the page happened to contain,
    which on page four of "stripe" is not the same as ranking the results. The
    bands are what somebody typing a name means - the server *called* Linear,
    then names merely containing it, then descriptions that mention it.
    """
    return case(
        (McpRegistryServer.name.ilike(f"{needle}%"), _BAND_NAME_STARTS),
        (McpRegistryServer.name.ilike(f"%{needle}%"), _BAND_NAME_HOLDS),
        else_=_BAND_ELSEWHERE,
    )


def _matching(query: str) -> Any:
    """The filter one query makes, or nothing for a blank one.

    A blank query is every row rather than none: unlike the in-memory version
    this replaced, the table can be paged, so "all of them" is an answer a
    listing can give.
    """
    needle = query.strip()
    if not needle:
        return None
    like = f"%{needle}%"
    return or_(
        McpRegistryServer.name.ilike(like),
        McpRegistryServer.description.ilike(like),
        McpRegistryServer.host.ilike(like),
    )


async def search(
    db: AsyncSession, *, query: str = "", skip: int = 0, limit: int = 50
) -> tuple[list[McpRegistryServer], int]:
    """One page of matching servers, best first, and how many matched in total.

    The total is a second query rather than `len(rows)`, because a pager has to
    say how many pages there are and a page cannot count what it does not hold.

    Ordered by band, then by name length, then by name: the length is what puts
    `Stripe` above `Sweden Payments (Stripe - EPS)`, and the name after it makes
    the order total, so page two does not repeat a row page one already showed.
    """
    condition = _matching(query)

    rows = select(McpRegistryServer)
    counted = select(func.count()).select_from(McpRegistryServer)
    if condition is not None:
        rows = rows.where(condition)
        counted = counted.where(condition)

    needle = query.strip()
    order: list[Any] = []
    if needle:
        order.append(_bands(needle))
    order += [func.length(McpRegistryServer.name), McpRegistryServer.name]

    result = await db.execute(rows.order_by(*order).offset(skip).limit(limit))
    total = await db.scalar(counted) or 0
    return list(result.scalars().all()), total


async def get(db: AsyncSession, server_id: str) -> McpRegistryServer | None:
    result = await db.execute(select(McpRegistryServer).where(McpRegistryServer.id == server_id))
    return result.scalar_one_or_none()


async def count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(McpRegistryServer)) or 0


async def upsert_many(db: AsyncSession, entries: Sequence[dict[str, Any]]) -> int:
    """Write these servers, replacing what a previous sync wrote for the same ids.

    One statement per batch rather than a read-then-write per row: 5,703 round
    trips is a sync somebody cancels. `ON CONFLICT DO UPDATE` is what makes a
    re-sync idempotent - the second run stamps `synced_at` and changes nothing
    else unless upstream did.
    """
    if not entries:
        return 0
    now = datetime.now(UTC)
    statement = insert(McpRegistryServer).values([{**entry, "synced_at": now} for entry in entries])
    statement = statement.on_conflict_do_update(
        index_elements=[McpRegistryServer.id],
        set_={
            "name": statement.excluded.name,
            "description": statement.excluded.description,
            "url": statement.excluded.url,
            "host": statement.excluded.host,
            "synced_at": statement.excluded.synced_at,
        },
    )
    await db.execute(statement)
    await db.flush()
    return len(entries)


async def delete_stale(db: AsyncSession, before: datetime) -> int:
    """Drop rows an earlier sync wrote and this one did not.

    A server the upstream registry stopped listing has to leave, or the mirror
    only ever grows and a delisted endpoint stays offerable for ever. Keyed on
    `synced_at` rather than on a diff, because the sync already stamped every row
    it touched and comparing two sets of five thousand ids is the same answer at
    more cost.
    """
    result = await db.execute(delete(McpRegistryServer).where(McpRegistryServer.synced_at < before))
    await db.flush()
    return result.rowcount or 0
