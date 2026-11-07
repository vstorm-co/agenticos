"""Saved accounts determine Connected before catalog filtering and pagination."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.mcp_connection import McpConnection
from app.db.models.mcp_registry_server import McpRegistryServer
from app.db.models.mcp_server_check import CheckOutcome, McpServerCheck
from app.repositories import (
    mcp_connection_repo,
    mcp_registry_server_repo,
    mcp_server_check_repo,
    resource_grant_repo,
)
from app.services import mcp_catalog, mcp_listing
from app.services.mcp_catalog import CatalogAuth, CatalogEntry

pytestmark = pytest.mark.anyio


@dataclass
class ListingRepositories:
    organization: AsyncMock
    personal: AsyncMock
    registry: AsyncMock
    search: AsyncMock
    checks: AsyncMock
    grants: AsyncMock


@pytest.fixture
def caller() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> tuple[CatalogEntry, ...]:
    entries = tuple(
        CatalogEntry(
            key=f"server-{index:02}",
            name=f"Server {index:02}",
            description=f"Development service {index:02}",
            category="development",
            auth=CatalogAuth.TOKEN,
            url=f"https://server-{index:02}.example.test/mcp",
        )
        for index in range(62)
    )
    monkeypatch.setattr(mcp_catalog, "CATALOG", entries)
    return entries


@pytest.fixture
def repositories(monkeypatch: pytest.MonkeyPatch) -> ListingRepositories:
    repositories = ListingRepositories(
        organization=AsyncMock(return_value=([], 0)),
        personal=AsyncMock(return_value=([], 0)),
        registry=AsyncMock(return_value=[]),
        search=AsyncMock(return_value=([], 0)),
        checks=AsyncMock(return_value={}),
        grants=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(mcp_connection_repo, "list_org_scoped", repositories.organization)
    monkeypatch.setattr(mcp_connection_repo, "list_for_user", repositories.personal)
    monkeypatch.setattr(mcp_registry_server_repo, "for_connections", repositories.registry)
    monkeypatch.setattr(mcp_registry_server_repo, "search", repositories.search)
    monkeypatch.setattr(mcp_registry_server_repo, "count", AsyncMock(return_value=4_000))
    monkeypatch.setattr(mcp_server_check_repo, "get_many", repositories.checks)
    monkeypatch.setattr(resource_grant_repo, "list_shared_ids", repositories.grants)
    return repositories


def _connection(
    caller: AuthContext,
    *,
    name: str,
    url: str,
    key: str | None = None,
    scope: Literal["org", "user"] = "org",
    visibility: str = "org",
    created_by: UUID | None = None,
    auth: Literal["bearer", "oauth"] = "bearer",
    token: bool = False,
) -> McpConnection:
    return McpConnection(
        id=uuid4(),
        scope=scope,
        organization_id=caller.organization_id if scope == "org" else None,
        user_id=caller.user_id if scope == "user" else None,
        created_by_user_id=created_by,
        visibility=visibility,
        name=name,
        url=url,
        catalog_key=key,
        auth_type=auth,
        auth_token="test-ciphertext" if token else None,
        is_enabled=False,
        last_status="error",
    )


def _mirrored(
    *, key: str = "registry/off-page", category: str = "development"
) -> McpRegistryServer:
    return McpRegistryServer(
        id=key,
        name="Registry server",
        description="Registry development service",
        url=f"https://{key.rsplit('/', 1)[-1]}.example.test/mcp",
        host=f"{key.rsplit('/', 1)[-1]}.example.test",
        category=category,
    )


def _check(key: str, outcome: CheckOutcome) -> McpServerCheck:
    return McpServerCheck(
        key=key,
        outcome=outcome,
        source="registry",
        checked_at=datetime.now(UTC),
        tools=None,
        read_only_tools=None,
    )


async def test_connected_includes_custom_and_off_page_servers_without_catalog_search(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    organization = [
        _connection(caller, name="grafana", key=catalog[2].key, url=catalog[2].url),
        _connection(caller, name="linear", key=catalog[61].key, url=catalog[61].url),
        _connection(caller, name="netbox", url="https://netbox.example.test/mcp"),
    ]
    repositories.organization.return_value = organization, len(organization)

    found = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")

    assert [row.name for row in found.items] == ["Server 02", "Server 61", "netbox"]
    assert found.total == 3
    assert found.registry_total == 4_000
    assert found.items[-1].custom
    assert {account for row in found.items for account in row.connection_ids or ()} == {
        account.id for account in organization
    }
    repositories.search.assert_not_awaited()


async def test_accounts_share_one_card_using_catalog_key_then_url_then_legacy_name(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    entry = catalog[61]
    keyed = _connection(caller, name=catalog[0].key, key=entry.key, url=catalog[0].url)
    by_url = _connection(
        caller,
        name="personal-workspace",
        url=f" {entry.url.removesuffix('/mcp').upper()}/mcp/// ",
        scope="user",
    )
    legacy = _connection(
        caller, name=entry.key, url="https://former-host.example.test/mcp", scope="user"
    )
    custom = _connection(caller, name="netbox-work", url="https://netbox.example.test/mcp")
    custom_personal = _connection(
        caller, name="netbox-personal", url=" HTTPS://NETBOX.EXAMPLE.TEST/mcp/ ", scope="user"
    )
    repositories.organization.return_value = [keyed, custom], 2
    repositories.personal.return_value = [by_url, legacy, custom_personal], 3

    found = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")

    assert found.total == 2
    assert found.items[0].key == entry.key
    assert found.items[0].connection_ids == (keyed.id, by_url.id, legacy.id)
    assert found.items[1].connection_ids == (custom.id, custom_personal.id)
    assert found.items[1].custom


async def test_custom_card_identity_survives_removing_its_first_account(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    first = _connection(caller, name="netbox-work", url="https://netbox.example.test/mcp")
    second = _connection(caller, name="netbox-other", url=" HTTPS://NETBOX.EXAMPLE.TEST/mcp/// ")
    personal = _connection(
        caller, name="netbox-personal", url="https://netbox.example.test/mcp/", scope="user"
    )
    repositories.organization.return_value = [first, second], 2
    repositories.personal.return_value = [personal], 1
    before = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")

    repositories.organization.return_value = [second], 1
    without_first = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")
    repositories.organization.return_value = [], 0
    personal_only = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")

    assert before.total == without_first.total == personal_only.total == 1
    assert before.items[0].key == without_first.items[0].key == personal_only.items[0].key
    assert before.items[0].connection_ids == (first.id, second.id, personal.id)
    assert without_first.items[0].connection_ids == (second.id, personal.id)
    assert personal_only.items[0].connection_ids == (personal.id,)


@pytest.mark.parametrize(
    ("first_path", "second_path"),
    [
        ("/Finance/mcp", "/finance/mcp"),
        ("/mcp?tenant=Finance", "/mcp?tenant=finance"),
        ("/mcp?token=value/", "/mcp?token=value"),
    ],
)
async def test_distinct_custom_endpoints_keep_their_own_cards_and_urls(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
    first_path: str,
    second_path: str,
) -> None:
    accounts = [
        _connection(
            caller,
            name=f"account-{index}",
            url=f"https://gateway.example.test{path}",
            auth="oauth",
        )
        for index, path in enumerate((first_path, second_path))
    ]
    repositories.organization.return_value = accounts, len(accounts)

    found = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")

    assert found.total == 2
    assert len({row.key for row in found.items}) == 2
    assert [(row.url, row.connection_ids) for row in found.items] == [
        (account.url, (account.id,)) for account in accounts
    ]


@pytest.mark.parametrize("state", ["all", "connected"])
async def test_search_finds_a_custom_group_by_another_accounts_name(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
    state: Literal["all", "connected"],
) -> None:
    work = _connection(caller, name="work-account", url="https://netbox.example.test/mcp")
    personal = _connection(
        caller, name="personal-workspace", url="https://netbox.example.test/mcp/", scope="user"
    )
    repositories.organization.return_value = [work], 1
    repositories.personal.return_value = [personal], 1

    found = await mcp_listing.page(
        mock_db_session, ctx=caller, state=state, query=" PERSONAL-WORKSPACE "
    )

    assert found.total == 1
    assert len(found.items) == 1
    assert found.items[0].name == personal.name
    assert found.items[0].connection_ids == (work.id, personal.id)


@pytest.mark.parametrize(
    ("auth", "expected_name"),
    [("token", "token-account"), ("oauth", "oauth-account"), ("none", "open-account")],
)
async def test_sign_in_filter_matches_any_account_in_a_custom_group(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
    auth: str,
    expected_name: str,
) -> None:
    url = "https://netbox.example.test/mcp"
    token = _connection(caller, name="token-account", url=url, token=True)
    oauth = _connection(caller, name="oauth-account", url=url, auth="oauth", scope="user")
    no_auth = _connection(caller, name="open-account", url=url, scope="user")
    repositories.organization.return_value = [token], 1
    repositories.personal.return_value = [oauth, no_auth], 2
    unfiltered = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")

    found = await mcp_listing.page(mock_db_session, ctx=caller, state="connected", auth=auth)

    assert found.total == 1
    assert found.items[0].key == unfiltered.items[0].key
    assert found.items[0].name == expected_name
    assert found.items[0].auth == auth
    assert found.items[0].connection_ids == (token.id, oauth.id, no_auth.id)


@pytest.mark.parametrize("state", ["all", "connected"])
async def test_a_custom_server_bookmark_resolves_its_opaque_key_without_losing_accounts(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
    state: Literal["all", "connected"],
) -> None:
    work = _connection(caller, name="work-account", url="https://netbox.example.test/mcp")
    personal = _connection(caller, name="personal-account", url=work.url, scope="user")
    repositories.organization.return_value = [work], 1
    repositories.personal.return_value = [personal], 1
    connected = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")
    key = connected.items[0].key

    found = await mcp_listing.page(mock_db_session, ctx=caller, state=state, query=key)

    assert found.total == 1
    assert found.items[0].key == key
    assert found.items[0].connection_ids == (work.id, personal.id)
    assert found.items[0].custom


async def test_connected_resolves_only_saved_registry_identities_even_after_a_failed_check(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    registry = _mirrored()
    account = _connection(caller, name="registry-work", key=registry.id, url=registry.url)
    repositories.organization.return_value = [account], 1
    repositories.registry.return_value = [registry]
    repositories.checks.return_value = {registry.id: _check(registry.id, CheckOutcome.UNREACHABLE)}

    found = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")

    assert found.total == 1
    assert found.items[0].key == registry.id
    assert found.items[0].connection_ids == (account.id,)
    assert not found.items[0].custom
    assert not found.items[0].reviewed
    assert found.items[0].check is not None
    assert found.items[0].check.outcome == "unreachable"
    assert repositories.registry.await_args.kwargs == {
        "keys": {registry.id},
        "urls": {registry.url},
        "names": {account.name},
    }
    repositories.search.assert_not_awaited()


async def test_a_registry_key_collision_keeps_curated_metadata_and_one_connected_card(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    entry = catalog[-1]
    account = _connection(caller, name="workspace", key=entry.key, url=entry.url)
    repositories.organization.return_value = [account], 1
    repositories.registry.return_value = [_mirrored(key=entry.key, category="other")]

    found = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")

    assert found.total == 1
    assert len(found.items) == 1
    assert found.items[0].name == entry.name
    assert found.items[0].description == entry.description
    assert found.items[0].category == entry.category
    assert found.items[0].reviewed
    assert found.items[0].connection_ids == (account.id,)


async def test_a_self_hosted_catalog_server_keeps_its_saved_account_with_a_configured_url(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = replace(catalog[-1], url="")
    monkeypatch.setattr(mcp_catalog, "CATALOG", (*catalog[:-1], entry))
    account = _connection(
        caller, name="self-hosted-work", key=entry.key, url="https://internal.example.test/mcp"
    )
    repositories.organization.return_value = [account], 1

    found = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")

    assert found.total == 1
    assert found.items[0].key == entry.key
    assert found.items[0].url is None
    assert not found.items[0].custom
    assert found.items[0].connection_ids == (account.id,)


async def test_connected_paginates_servers_after_grouping_accounts(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    accounts = [
        _connection(caller, name=entry.key, key=entry.key, url=entry.url) for entry in catalog
    ]
    custom = _connection(caller, name="netbox", url="https://netbox.example.test/mcp")
    duplicate = _connection(caller, name="extra-account", key=catalog[-1].key, url=catalog[-1].url)
    repositories.organization.return_value = [*accounts, custom, duplicate], len(accounts) + 2

    first = await mcp_listing.page(mock_db_session, ctx=caller, state="connected", limit=50)
    second = await mcp_listing.page(
        mock_db_session, ctx=caller, state="connected", skip=50, limit=50
    )

    assert first.total == second.total == 63
    assert len(first.items) == 50
    assert len(second.items) == 13
    keys = [row.key for row in (*first.items, *second.items)]
    assert keys[:-1] == [entry.key for entry in catalog]
    assert len(keys) == len(set(keys))
    assert second.items[-2].connection_ids == (accounts[-1].id, duplicate.id)
    assert second.items[-1].connection_ids == (custom.id,)
    assert second.items[-1].custom


@pytest.mark.parametrize(
    ("query", "category", "auth", "expected"),
    [
        (" server 61 ", "development", "token", "catalog"),
        ("NETBOX", "custom", "oauth", "custom"),
        ("netbox.example.test", "custom", "oauth", "custom"),
        ("netbox", "development", "", None),
        ("", "custom", "none", None),
    ],
)
async def test_connected_combines_search_category_and_sign_in_before_counting(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
    query: str,
    category: str,
    auth: str,
    expected: str | None,
) -> None:
    entry = catalog[61]
    custom = _connection(caller, name="NetBox", url="https://netbox.example.test/mcp", auth="oauth")
    repositories.organization.return_value = (
        [
            _connection(caller, name="workspace", key=entry.key, url=entry.url),
            custom,
        ],
        2,
    )

    found = await mcp_listing.page(
        mock_db_session, ctx=caller, state="connected", query=query, category=category, auth=auth
    )

    assert found.total == (0 if expected is None else 1)
    if expected is None:
        assert found.items == ()
    elif expected == "catalog":
        assert found.items[0].key == entry.key
    else:
        assert found.items[0].custom
        assert found.items[0].connection_ids == (custom.id,)


async def test_sign_in_filter_excludes_the_unchecked_registry_token_guess(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    checked = _mirrored(key="registry/checked")
    unchecked = _mirrored(key="registry/unchecked")
    accounts = [
        _connection(caller, name=row.id, key=row.id, url=row.url) for row in (checked, unchecked)
    ]
    repositories.personal.return_value = accounts, len(accounts)
    repositories.registry.return_value = [checked, unchecked]
    repositories.checks.return_value = {checked.id: _check(checked.id, CheckOutcome.TOKEN)}

    all_connected = await mcp_listing.page(mock_db_session, ctx=caller, state="connected")
    filtered = await mcp_listing.page(mock_db_session, ctx=caller, state="connected", auth="token")

    assert all_connected.total == 2
    assert filtered.total == 1
    assert [row.key for row in filtered.items] == [checked.id]


async def test_builder_sees_organization_audience_owner_and_grants_without_private_leaks(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    builder = AuthContext(
        user_id=caller.user_id, organization_id=caller.organization_id, role=OrgRoleName.BUILDER
    )
    public, owned, granted, denied = [
        _connection(
            caller,
            name=entry.key,
            key=entry.key,
            url=entry.url,
            visibility="org" if index == 0 else "private",
            created_by=caller.user_id if index == 1 else uuid4(),
        )
        for index, entry in enumerate(catalog[:4])
    ]
    repositories.organization.return_value = [public, owned, granted, denied], 4
    repositories.grants.return_value = [granted.id]

    found = await mcp_listing.page(mock_db_session, ctx=builder, state="connected")

    assert [row.key for row in found.items] == [catalog[index].key for index in range(3)]
    assert found.total == 3
    assert denied.id not in {account for row in found.items for account in row.connection_ids or ()}


async def test_member_without_organization_management_sees_only_personal_accounts(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    member = AuthContext(
        user_id=caller.user_id, organization_id=caller.organization_id, role=OrgRoleName.MEMBER
    )
    personal = _connection(
        caller, name="own-account", key=catalog[-1].key, url=catalog[-1].url, scope="user"
    )
    repositories.personal.return_value = [personal], 1

    found = await mcp_listing.page(mock_db_session, ctx=member, state="connected")

    assert found.total == 1
    assert found.items[0].connection_ids == (personal.id,)
    repositories.organization.assert_not_awaited()
    repositories.personal.assert_awaited_once_with(mock_db_session, user_id=caller.user_id)


async def test_a_context_without_a_subject_has_no_connected_accounts(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    found = await mcp_listing.page(
        mock_db_session, ctx=AuthContext.anonymous(caller.organization_id), state="connected"
    )

    assert found.items == ()
    assert found.total == 0
    repositories.organization.assert_not_awaited()
    repositories.personal.assert_not_awaited()
    repositories.registry.assert_not_awaited()


async def test_a_key_without_personal_run_scope_does_not_read_personal_accounts(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    scoped_key = AuthContext(
        user_id=caller.user_id,
        organization_id=caller.organization_id,
        role=OrgRoleName.OWNER,
        key_scopes=frozenset({Perm.AGENTS_VIEW}),
    )

    found = await mcp_listing.page(mock_db_session, ctx=scoped_key, state="connected")

    assert found.total == 0
    assert found.items == ()
    repositories.organization.assert_not_awaited()
    repositories.personal.assert_not_awaited()


async def test_all_counts_custom_servers_and_pages_them_after_the_catalog(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    customs = [
        _connection(caller, name=f"custom-{index}", url=f"https://custom-{index}.example.test/mcp")
        for index in range(3)
    ]
    repositories.organization.return_value = customs, len(customs)

    boundary = await mcp_listing.page(mock_db_session, ctx=caller, skip=60, limit=3)
    last = await mcp_listing.page(mock_db_session, ctx=caller, skip=63, limit=3)

    assert boundary.total == last.total == 65
    assert [row.key for row in boundary.items[:2]] == [catalog[60].key, catalog[61].key]
    assert boundary.items[-1].connection_ids == (customs[0].id,)
    assert [row.connection_ids for row in last.items] == [(account.id,) for account in customs[1:]]


async def test_not_connected_excludes_curated_accounts_before_pagination_and_counts(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    connected = _connection(caller, name="workspace", key=catalog[0].key, url=catalog[0].url)
    registry = _mirrored()
    registry_account = _connection(
        caller, name="registry-account", key=registry.id, url=registry.url
    )
    custom = _connection(caller, name="netbox", url="https://netbox.example.test/mcp")
    repositories.organization.return_value = [connected, registry_account, custom], 3
    repositories.registry.return_value = [registry]

    found = await mcp_listing.page(mock_db_session, ctx=caller, state="not-connected", limit=50)

    assert found.total == 61
    assert [row.key for row in found.items] == [entry.key for entry in catalog[1:51]]
    assert all(row.connection_ids == () for row in found.items)
    excluded = repositories.search.await_args.kwargs["excluded_ids"]
    assert {catalog[0].key, registry.id} <= excluded
    assert len(excluded) == 3


async def test_a_saved_exact_key_precedes_related_results_in_a_bounded_bookmark_lookup(
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    target = _mirrored(key="registry/target")
    related = [_mirrored(key=f"registry/related-{index}") for index in range(12)]
    for server in related:
        server.description = f"Alternative to {target.id}"
    repositories.registry.return_value = [*related, target]
    accounts = [
        _connection(caller, name=server.id, key=server.id, url=server.url)
        for server in [*related, target]
    ]
    repositories.organization.return_value = accounts, len(accounts)

    found = await mcp_listing.page(
        mock_db_session, ctx=caller, query=target.id, state="connected", limit=10
    )

    assert found.total == 13
    assert found.items[0].key == target.id
    assert len(found.items) == 10


@pytest.mark.parametrize("state", ["all", "connected", "not-connected"])
@pytest.mark.parametrize("query", ["work-iq", "WORK-IQ", " work-iq "])
async def test_exact_curated_keys_match_when_the_slug_is_absent_from_display_metadata(
    state: Literal["all", "connected", "not-connected"],
    query: str,
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = replace(
        catalog[0],
        key="work-iq",
        name="Microsoft Work IQ",
        description="Company knowledge",
        url="https://workspace.example.test/mcp",
    )
    monkeypatch.setattr(mcp_catalog, "CATALOG", (entry,))
    if state == "connected":
        account = _connection(caller, name="work", key=entry.key, url=entry.url)
        repositories.organization.return_value = [account], 1

    found = await mcp_listing.page(
        mock_db_session,
        ctx=caller,
        query=query,
        state=state,
        category=entry.category,
        auth=entry.auth.value,
    )

    assert found.total == 1
    assert [row.key for row in found.items] == [entry.key]


@pytest.mark.parametrize("state", ["all", "connected"])
async def test_pruned_registry_metadata_does_not_rename_a_saved_server_bookmark(
    state: Literal["all", "connected"],
    caller: AuthContext,
    catalog: tuple[CatalogEntry, ...],
    repositories: ListingRepositories,
    mock_db_session: AsyncSession,
) -> None:
    key = "registry/removed-service"
    first = _connection(caller, name="work", key=key, url="https://work.example.test/mcp")
    second = _connection(
        caller, name="personal", key=key, url="https://home.example.test/mcp", scope="user"
    )
    repositories.organization.return_value = [first], 1
    repositories.personal.return_value = [second], 1
    repositories.registry.return_value = []

    found = await mcp_listing.page(mock_db_session, ctx=caller, query=key, state=state)

    assert found.total == 1
    assert found.items[0].key == key
    assert found.items[0].connection_ids == (first.id, second.id)
    assert found.items[0].custom


async def test_new_google_entries_have_bundled_checks_without_rebootstrapping(
    repositories: ListingRepositories,
) -> None:
    entries = await mcp_listing.curated(AsyncMock())
    calendar = next(entry for entry in entries if entry.key == "google-calendar")
    assert calendar.verified
    assert calendar.check is not None
    assert calendar.check.outcome == "sign_in"


def test_a_local_remote_failure_is_not_hidden_by_a_bundled_success() -> None:
    entry = mcp_catalog.BY_KEY["google-calendar"]
    check = McpServerCheck(
        key=entry.key, source="catalog", outcome="unreachable", checked_at=datetime.now(UTC)
    )
    assert not mcp_listing._curated(entry, check).verified


def test_an_old_self_hosted_check_does_not_hide_the_new_remote_bigquery() -> None:
    entry = mcp_catalog.BY_KEY["bigquery"]
    check = McpServerCheck(
        key=entry.key, source="catalog", outcome="self_hosted", checked_at=datetime.now(UTC)
    )
    result = mcp_listing._curated(entry, check)
    assert result.verified
    assert result.url == "https://bigquery.googleapis.com/mcp"
