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

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import mcp_registry_server_repo
from app.services import mcp_catalog
from app.services.mcp_catalog import CatalogEntry


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


def _curated(entry: CatalogEntry) -> ListedServer:
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
    )


async def page(
    db: AsyncSession, *, query: str = "", category: str = "", skip: int = 0, limit: int = 50
) -> ServerPage:
    """One page of the joined list.

    Curated entries first and in catalog order, which is a judgement no substring
    test improves on at a hundred rows. Registry rows follow, ranked in SQL,
    because five thousand have no such order and ranking a page is ranking
    whatever that page happened to contain.

    A **category narrows to the catalog alone**: the mirror has no categories, so
    answering with mirror rows would put uncategorised servers under a heading
    that says otherwise.
    """
    curated = mcp_catalog.matching(query, category=category)
    items = [_curated(entry) for entry in curated[skip : skip + limit]]
    mirror_total = await mcp_registry_server_repo.count(db)

    if category:
        return ServerPage(items=tuple(items), total=len(curated), registry_total=mirror_total)

    # Whatever room the page has left after the curated rows, offset by however
    # many of them the earlier pages consumed - so a page boundary landing inside
    # the join neither skips a server nor shows one twice.
    wanted = limit - len(items)
    servers, matched = await mcp_registry_server_repo.search(
        db, query=query, skip=max(0, skip - len(curated)), limit=max(wanted, 1)
    )
    if wanted > 0:
        items += [
            ListedServer(
                key=server.id,
                name=server.name,
                description=server.description,
                category="other",
                auth="token",
                url=server.url,
                docs_url=None,
                token_hint=None,
                icon=None,
                reviewed=False,
            )
            for server in servers[:wanted]
        ]

    return ServerPage(items=tuple(items), total=len(curated) + matched, registry_total=mirror_total)
