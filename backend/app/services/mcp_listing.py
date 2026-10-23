"""One paged list of connectable servers: the catalog, then the registry mirror.

The join lives here rather than in the route because it is arithmetic, and the
route's job is to validate, delegate and return. Getting it wrong is invisible
from the page: with 99 curated entries and 50 to a page, page two ends 49 rows
into the catalog and page three begins one row in, so an off-by-one skips a
server or shows it twice on a list where nobody would notice which.

Why the two are joined at all: the curated catalog is a hundred entries somebody
checked, and the mirror is 5,703 nobody did. Presenting them as two screens made
the second one unreachable except by search, which reads as a catalog of a
hundred. One list, with `reviewed` on the row saying which kind it is.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mcp_registry_server import McpRegistryServer
from app.db.models.mcp_server_check import CheckOutcome, McpServerCheck
from app.repositories import mcp_registry_server_repo, mcp_server_check_repo
from app.services import mcp_catalog
from app.services.mcp_audit import auth_found, verified
from app.services.mcp_catalog import CatalogEntry


@dataclass(frozen=True)
class ListedCheck:
    """What the last catalog check found, as much of it as a row shows."""

    outcome: str
    checked_at: datetime
    tools: int | None
    """How many tools it listed without a credential; None where it could not."""

    read_only_tools: int | None


@dataclass(frozen=True)
class ListedServer:
    """One row of the list, from whichever source produced it."""

    key: str
    name: str
    description: str
    category: str
    auth: str
    url: str | None
    docs_url: str | None
    token_hint: str | None
    icon: str | None
    reviewed: bool
    verified: bool
    """The last check found it answering the way the row says it does."""

    check: ListedCheck | None


@dataclass(frozen=True)
class ServerPage:
    """One page, and the two counts a pager and a count line need."""

    items: tuple[ListedServer, ...]
    total: int
    """Matches across both sources, so a pager knows how many pages there are."""

    registry_total: int
    """What the mirror holds, which is what the list *reaches* rather than what
    this page matched. Zero until `agenticos cmd mcp-registry-sync` has run."""


async def mirror_size(db: AsyncSession) -> int:
    """How many servers the mirror holds.

    Here rather than reached for from a route: a route calls services and never a
    repository, and `tests/test_route_layering.py` is what says so. It caught
    this one importing `mcp_registry_server_repo` for a single count.
    """
    return await mcp_registry_server_repo.count(db)


def _listed_check(check: McpServerCheck | None) -> ListedCheck | None:
    if check is None:
        return None
    return ListedCheck(
        outcome=check.outcome,
        checked_at=check.checked_at,
        tools=check.tools,
        read_only_tools=check.read_only_tools,
    )


def _curated(entry: CatalogEntry, check: McpServerCheck | None) -> ListedServer:
    return ListedServer(
        key=entry.key,
        name=entry.name,
        description=entry.description,
        category=entry.category,
        auth=entry.auth.value,
        url=entry.url or None,
        docs_url=entry.docs_url or None,
        token_hint=entry.token_hint or None,
        icon=entry.icon or None,
        reviewed=True,
        verified=check is not None and verified(check.outcome, declared=entry.auth.value),
        check=_listed_check(check),
    )


def _mirrored(server: McpRegistryServer, check: McpServerCheck | None) -> ListedServer:
    """A registry row, with what its check found standing in for what nobody wrote.

    The registry states no auth, so the check's finding is the only honest one;
    a listing never checked keeps the old guess of a token, which is what the
    form can ask for without promising a sign-in button that may not work.
    """
    found = auth_found(CheckOutcome(check.outcome)) if check is not None else None
    return ListedServer(
        key=server.id,
        name=server.name,
        description=server.description,
        category=server.category,
        auth=found or "token",
        url=server.url,
        docs_url=None,
        token_hint=None,
        icon=None,
        reviewed=False,
        verified=check is not None and verified(check.outcome),
        check=_listed_check(check),
    )


async def curated(db: AsyncSession) -> tuple[ListedServer, ...]:
    """The whole curated catalog, each entry with its last check."""
    checks = await mcp_server_check_repo.get_many(db, [entry.key for entry in mcp_catalog.CATALOG])
    return tuple(_curated(entry, checks.get(entry.key)) for entry in mcp_catalog.CATALOG)


async def page(
    db: AsyncSession,
    *,
    query: str = "",
    category: str = "",
    auth: str = "",
    skip: int = 0,
    limit: int = 50,
) -> ServerPage:
    """One page of the joined list.

    Curated entries first and in catalog order, which is a judgement no substring
    test improves on at a hundred rows. Registry rows follow, ranked in SQL,
    because five thousand have no such order and ranking a page is ranking
    whatever that page happened to contain.

    A category reaches the mirror too, through the category each listing was
    given at sync. `auth` keeps curated entries that declare it and mirrored
    ones a check found asking for it. Mirrored listings a check found dead,
    broken or duplicated are not on the list at all.
    """
    matched_curated = tuple(
        entry
        for entry in mcp_catalog.matching(query, category=category)
        if not auth or entry.auth.value == auth
    )
    shown = matched_curated[skip : skip + limit]
    checks = await mcp_server_check_repo.get_many(db, [entry.key for entry in shown])
    items = [_curated(entry, checks.get(entry.key)) for entry in shown]
    mirror_total = await mcp_registry_server_repo.count(db)

    # Whatever room the page has left after the curated rows, offset by however
    # many of them the earlier pages consumed - so a page boundary landing inside
    # the join neither skips a server nor shows one twice.
    wanted = limit - len(items)
    servers, matched = await mcp_registry_server_repo.search(
        db,
        query=query,
        category=category,
        auth=auth,
        skip=max(0, skip - len(matched_curated)),
        limit=max(wanted, 1),
    )
    if wanted > 0:
        items += [_mirrored(server, check) for server, check in servers[:wanted]]

    return ServerPage(
        items=tuple(items), total=len(matched_curated) + matched, registry_total=mirror_total
    )
