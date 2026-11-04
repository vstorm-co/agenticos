"""The server listing keeps its permission gate and validates filter state."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.main import app
from app.services import mcp_listing

pytestmark = pytest.mark.anyio

URL = f"{settings.API_V1_STR}/agents/mcp-servers"


@pytest.fixture
def caller() -> AuthContext:
    context = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    return context


async def test_listing_passes_connection_state_and_filters_and_serializes_grouped_account_ids(
    client: AsyncClient, caller: AuthContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_ids = (uuid4(), uuid4())
    listing = AsyncMock(
        return_value=mcp_listing.ServerPage(
            items=(
                mcp_listing.ListedServer(
                    key=str(account_ids[0]),
                    name="NetBox",
                    description="",
                    category="custom",
                    auth="oauth",
                    url="https://netbox.example.test/mcp",
                    docs_url=None,
                    token_hint=None,
                    icon=None,
                    reviewed=True,
                    verified=False,
                    check=None,
                    custom=True,
                    connection_ids=account_ids,
                ),
            ),
            total=51,
            registry_total=4_000,
        )
    )
    monkeypatch.setattr(mcp_listing, "page", listing)

    response = await client.get(
        URL,
        params={
            "state": "connected",
            "q": "NetBox",
            "category": "custom",
            "auth": "oauth",
            "skip": 50,
            "limit": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 51
    assert payload["registry_total"] == 4_000
    assert payload["items"][0]["custom"]
    assert payload["items"][0]["connection_ids"] == [str(account_id) for account_id in account_ids]
    assert listing.await_args.kwargs == {
        "ctx": caller,
        "query": "NetBox",
        "category": "custom",
        "auth": "oauth",
        "state": "connected",
        "skip": 50,
        "limit": 1,
    }


async def test_listing_defaults_to_all_servers(
    client: AsyncClient, caller: AuthContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = AsyncMock(return_value=mcp_listing.ServerPage(items=(), total=0, registry_total=0))
    monkeypatch.setattr(mcp_listing, "page", listing)

    response = await client.get(URL)

    assert response.status_code == 200
    assert listing.await_args.kwargs["state"] == "all"
    assert listing.await_args.kwargs["skip"] == 0
    assert listing.await_args.kwargs["limit"] == 50


async def test_an_unknown_connection_state_is_rejected(
    client: AsyncClient, caller: AuthContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = AsyncMock()
    monkeypatch.setattr(mcp_listing, "page", listing)

    response = await client.get(URL, params={"state": "enabled"})

    assert response.status_code == 422
    listing.assert_not_awaited()


async def test_a_bookmark_can_resolve_a_registry_key_longer_than_a_hundred_characters(
    client: AsyncClient, caller: AuthContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "com.example/" + "long-registry-service-" * 6
    listing = AsyncMock(return_value=mcp_listing.ServerPage(items=(), total=0, registry_total=0))
    monkeypatch.setattr(mcp_listing, "page", listing)

    response = await client.get(URL, params={"q": key, "limit": 10})

    assert response.status_code == 200
    assert listing.await_args.kwargs["query"] == key


async def test_listing_requires_agents_view_even_for_connected_servers(
    client: AsyncClient, caller: AuthContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoped_key = AuthContext(
        user_id=caller.user_id,
        organization_id=caller.organization_id,
        role=caller.role,
        key_scopes=frozenset({Perm.AGENTS_RUN}),
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: scoped_key
    listing = AsyncMock()
    monkeypatch.setattr(mcp_listing, "page", listing)

    response = await client.get(URL, params={"state": "connected"})

    assert response.status_code == 403
    listing.assert_not_awaited()
