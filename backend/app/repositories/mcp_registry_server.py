"""Reading and refreshing the mirrored MCP registry."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.mcp_registry_server import McpRegistryServer
from app.db.models.mcp_server_check import NOT_OFFERED, McpServerCheck

_BAND_KEY_EXACT = -1
_BAND_NAME_STARTS = 0
_BAND_NAME_HOLDS = 1
_BAND_ELSEWHERE = 2


def _bands(needle: str) -> ColumnElement[int]:
    """Rank exact keys before name prefixes, name substrings and description matches.

    Ranking happens before pagination so bookmarks and subsequent pages use the
    same ordering across the whole mirror.
    """
    return case(
        (func.lower(McpRegistryServer.id) == needle.lower(), _BAND_KEY_EXACT),
        (McpRegistryServer.name.ilike(f"{needle}%"), _BAND_NAME_STARTS),
        (McpRegistryServer.name.ilike(f"%{needle}%"), _BAND_NAME_HOLDS),
        else_=_BAND_ELSEWHERE,
    )


def _matching(query: str) -> ColumnElement[bool] | None:
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
        func.lower(McpRegistryServer.id) == needle.lower(),
        McpRegistryServer.name.ilike(like),
        McpRegistryServer.description.ilike(like),
        McpRegistryServer.host.ilike(like),
    )


async def search(
    db: AsyncSession,
    *,
    query: str = "",
    category: str = "",
    auth: str = "",
    skip: int = 0,
    limit: int = 50,
    excluded_ids: set[str] | None = None,
) -> tuple[list[tuple[McpRegistryServer, McpServerCheck | None]], int]:
    """One page of matching servers, best first, each with its last check, and the total.

    The total is a second query rather than `len(rows)`, because a pager has to
    say how many pages there are and a page cannot count what it does not hold.

    Ordered by band, then by name length, then by name: the length is what puts
    `Stripe` above `Sweden Payments (Stripe - EPS)`, and the name after it makes
    the order total, so page two does not repeat a row page one already showed.

    A listing whose last check found it dead, broken or a duplicate of another
    is left out - in SQL, for the same reason the ranking is: filtering a page
    leaves it short. A listing never checked stays in; nothing says it is dead.
    `auth` narrows to listings a check found asking for that, so an unchecked
    listing is outside every auth filter.
    """
    checked = McpServerCheck.key == McpRegistryServer.id
    conditions: list[Any] = [
        or_(McpServerCheck.outcome.is_(None), McpServerCheck.outcome.not_in(NOT_OFFERED))
    ]
    if (condition := _matching(query)) is not None:
        conditions.append(condition)
    if category:
        conditions.append(McpRegistryServer.category == category)
    if auth:
        conditions.append(McpServerCheck.auth == auth)
    if excluded_ids:
        conditions.append(McpRegistryServer.id.not_in(excluded_ids))

    needle = query.strip()
    order: list[Any] = []
    if needle:
        order.append(_bands(needle))
    order += [func.length(McpRegistryServer.name), McpRegistryServer.name, McpRegistryServer.id]

    rows = (
        select(McpRegistryServer, McpServerCheck)
        .outerjoin(McpServerCheck, checked)
        .where(*conditions)
        .order_by(*order)
        .offset(skip)
        .limit(limit)
    )
    counted = (
        select(func.count())
        .select_from(McpRegistryServer)
        .outerjoin(McpServerCheck, checked)
        .where(*conditions)
    )
    result = await db.execute(rows)
    total = await db.scalar(counted) or 0
    return [(server, check) for server, check in result.tuples().all()], total


async def for_connections(
    db: AsyncSession, *, keys: set[str], urls: set[str], names: set[str]
) -> list[McpRegistryServer]:
    """Resolve only the registry identities accessible saved accounts name.

    URLs arrive with scheme/host case normalized and trailing path slashes
    removed; path and query case remain significant. Matching the stored URL the
    same way reaches older connections without a catalog key, without loading the whole mirror.
    Names are legacy catalog-key fallbacks, so they match the registry id rather
    than the publisher's display name.
    """
    if not keys and not urls and not names:
        return []
    url = func.trim(McpRegistryServer.url)
    origin_pattern = r"^[^:/?#]+://[^/?#]*"
    origin = func.substring(url, origin_pattern)
    remainder = func.regexp_replace(url, origin_pattern, "")
    normalized_url = func.concat(
        func.lower(origin),
        func.rtrim(func.substring(remainder, r"^[^?#]*"), "/"),
        func.coalesce(func.substring(remainder, r"[?#].*$"), ""),
    )
    result = await db.execute(
        select(McpRegistryServer)
        .where(
            or_(
                McpRegistryServer.id.in_(keys | names),
                normalized_url.in_(urls),
            )
        )
        .order_by(func.length(McpRegistryServer.name), McpRegistryServer.name, McpRegistryServer.id)
    )
    return list(result.scalars().all())


async def listings(db: AsyncSession) -> list[tuple[str, str]]:
    """Every mirrored server as `(id, url)` - what the catalog check calls."""
    result = await db.execute(
        select(McpRegistryServer.id, McpRegistryServer.url).order_by(McpRegistryServer.id)
    )
    return [(server_id, url) for server_id, url in result.tuples().all()]


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
            "category": statement.excluded.category,
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
    result = cast(
        CursorResult[Any],
        await db.execute(delete(McpRegistryServer).where(McpRegistryServer.synced_at < before)),
    )
    await db.flush()
    return result.rowcount or 0
