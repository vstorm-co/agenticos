"""One paged list of connectable servers: catalog, registry mirror and custom servers.

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

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.db.models.mcp_connection import McpConnection
from app.db.models.mcp_registry_server import McpRegistryServer
from app.db.models.mcp_server_check import CheckOutcome, McpServerCheck
from app.repositories import mcp_registry_server_repo, mcp_server_check_repo
from app.services import mcp_catalog
from app.services.mcp_audit import BUNDLED_CHECKS, StoredCheck, auth_found, verified
from app.services.mcp_catalog import CatalogEntry
from app.services.mcp_connection import McpConnectionService


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
    custom: bool = False
    connection_ids: tuple[UUID, ...] | None = None


@dataclass(frozen=True)
class ServerPage:
    """One page, and the two counts a pager and a count line need."""

    items: tuple[ListedServer, ...]
    total: int
    """Matching servers across all sources, counted before pagination."""

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


def _listed_check(check: McpServerCheck | StoredCheck | None) -> ListedCheck | None:
    if check is None:
        return None
    return ListedCheck(
        outcome=check.outcome,
        checked_at=check.checked_at,
        tools=check.tools,
        read_only_tools=check.read_only_tools,
    )


def _curated(entry: CatalogEntry, check: McpServerCheck | StoredCheck | None) -> ListedServer:
    # Updated installs may not rerun bootstrap. New catalog entries still have
    # the release's audit; locally checked remote failures keep precedence.
    # A self-hosted result cannot describe an entry that now has a hosted URL.
    if check is None or (check.outcome == CheckOutcome.SELF_HOSTED and entry.url):
        bundled = BUNDLED_CHECKS.get(entry.key)
        check = bundled if bundled is not None else check
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


def _normalize_url(url: str) -> str:
    """Ignore host case and trailing path slashes, preserving path and query case."""
    parts = urlsplit(url.strip())
    return parts._replace(netloc=parts.netloc.lower(), path=parts.path.rstrip("/")).geturl()


async def _connected(
    db: AsyncSession, ctx: AuthContext | None, *, query: str, auth: str
) -> list[ListedServer]:
    """Resolve only accessible saved accounts, including servers no longer offered.

    The account lists enforce the same ownership and audience checks as the
    management endpoints. Registry metadata is read only for these identities;
    neither the complete mirror nor the public registry is fetched.
    """
    if ctx is None:
        return []
    service = McpConnectionService(db)
    connections: list[McpConnection] = []
    if ctx.has(Perm.MCP_MANAGE):
        organization, _ = await service.list_for_org(ctx)
        connections.extend(organization)
    if ctx.user_id is not None and ctx.key_allows(Perm.AGENTS_RUN):
        personal, _ = await service.list_for_user(user_id=ctx.user_id)
        connections.extend(personal)
    if not connections:
        return []

    mirrored = await mcp_registry_server_repo.for_connections(
        db,
        keys={one.catalog_key for one in connections if one.catalog_key is not None},
        urls={_normalize_url(one.url) for one in connections},
        names={one.name for one in connections},
    )
    checks = await mcp_server_check_repo.get_many(
        db, [entry.key for entry in mcp_catalog.CATALOG] + [server.id for server in mirrored]
    )
    curated_keys = {entry.key for entry in mcp_catalog.CATALOG}
    entries = [
        *[_curated(entry, checks.get(entry.key)) for entry in mcp_catalog.CATALOG],
        *[
            _mirrored(server, checks.get(server.id))
            for server in mirrored
            if server.id not in curated_keys
        ],
    ]
    by_key = {entry.key: entry for entry in entries}
    by_url: dict[str, ListedServer] = {}
    for entry in entries:
        if entry.url:
            by_url.setdefault(_normalize_url(entry.url), entry)

    accounts: dict[str, list[McpConnection]] = {}
    customs: dict[tuple[str, str], list[McpConnection]] = {}
    for one in connections:
        entry = (
            by_key.get(one.catalog_key or "")
            or by_url.get(_normalize_url(one.url))
            or by_key.get(one.name)
        )
        if entry is None:
            identity = (
                ("catalog", one.catalog_key)
                if one.catalog_key
                else ("url", _normalize_url(one.url))
            )
            customs.setdefault(identity, []).append(one)
        else:
            accounts.setdefault(entry.key, []).append(one)

    rows = [
        replace(entry, connection_ids=tuple(one.id for one in accounts[entry.key]))
        for entry in entries
        if entry.key in accounts
    ]
    for group in customs.values():
        first = group[0]
        row = ListedServer(
            key=first.catalog_key
            or str(uuid5(NAMESPACE_URL, f"agenticos:mcp:{_normalize_url(first.url)}")),
            name=first.name,
            description="",
            category="custom",
            auth="oauth" if first.auth_type == "oauth" else "token" if first.auth_token else "none",
            url=first.url,
            docs_url=None,
            token_hint=None,
            icon=None,
            reviewed=True,
            verified=False,
            check=None,
            custom=True,
            connection_ids=tuple(one.id for one in group),
        )
        # A custom server has account names rather than a catalog name. Keep it
        # searchable through every account, even after folding them into one card.
        for one in group:
            candidate = replace(
                row,
                name=one.name,
                auth="oauth" if one.auth_type == "oauth" else "token" if one.auth_token else "none",
            )
            if _matches(candidate, query=query, category="", auth=auth):
                rows.append(candidate)
                break
    return rows


def _matches(row: ListedServer, *, query: str, category: str, auth: str) -> bool:
    if category and row.category != category:
        return False
    if auth:
        if row.auth != auth:
            return False
        # Unchecked mirrored entries have a token guess for the connect form,
        # but the Sign-in filter only promises what a check actually found.
        if not row.reviewed and (
            row.check is None or auth_found(CheckOutcome(row.check.outcome)) != auth
        ):
            return False
    needle = query.strip().lower()
    return (
        not needle
        or needle == row.key.lower()
        or any(
            needle in value.lower()
            for value in (row.name, row.description, row.url or "", row.category)
        )
    )


async def page(
    db: AsyncSession,
    *,
    query: str = "",
    category: str = "",
    auth: str = "",
    skip: int = 0,
    limit: int = 50,
    ctx: AuthContext | None = None,
    state: Literal["all", "connected", "not-connected"] = "all",
) -> ServerPage:
    """One page of the joined list.

    Curated entries first and in catalog order, which is a judgement no substring
    test improves on at a hundred rows. Registry rows follow, ranked in SQL,
    because five thousand have no such order and ranking a page is ranking
    whatever that page happened to contain.

    A category reaches the mirror too, through the category each listing was
    given at sync. `auth` keeps curated entries that declare it and mirrored
    ones a check found asking for it. Browsing hides mirrored listings a check
    found dead, broken or duplicated; Connected keeps their saved accounts
    manageable. Every filter is applied before counting and pagination.
    """
    connected = await _connected(db, ctx, query=query, auth=auth)
    mirror_total = await mcp_registry_server_repo.count(db)
    if state == "connected":
        matched = [
            row for row in connected if _matches(row, query=query, category=category, auth=auth)
        ]
        # Bookmarks resolve a key through a bounded search, even when many
        # descriptions mention it. Keep that exact identity on the first page.
        needle = query.strip().casefold()
        if needle:
            matched.sort(key=lambda row: row.key.casefold() != needle)
        return ServerPage(
            items=tuple(matched[skip : skip + limit]),
            total=len(matched),
            registry_total=mirror_total,
        )

    accounts = {row.key: row.connection_ids for row in connected}
    matched_curated = tuple(
        entry
        for entry in mcp_catalog.matching(query, category=category)
        if not auth or entry.auth.value == auth
        if state != "not-connected" or entry.key not in accounts
    )
    shown = matched_curated[skip : skip + limit]
    checks = await mcp_server_check_repo.get_many(db, [entry.key for entry in shown])
    items = [
        replace(_curated(entry, checks.get(entry.key)), connection_ids=accounts.get(entry.key, ()))
        for entry in shown
    ]

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
        excluded_ids=set(accounts) if state == "not-connected" else None,
    )
    if wanted > 0:
        items += [
            replace(_mirrored(server, check), connection_ids=accounts.get(server.id, ()))
            for server, check in servers[:wanted]
        ]

    customs = [
        row
        for row in connected
        if row.custom
        and state == "all"
        and _matches(row, query=query, category=category, auth=auth)
    ]
    custom_skip = max(0, skip - len(matched_curated) - matched)
    items += customs[custom_skip : custom_skip + max(0, limit - len(items))]

    return ServerPage(
        items=tuple(items),
        total=len(matched_curated) + matched + len(customs),
        registry_total=mirror_total,
    )
