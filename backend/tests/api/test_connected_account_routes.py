"""Connected accounts through the app (#2191).

A person's own accounts are theirs to connect with no organization permission; the
organization's take `mcp:manage` to connect or disconnect and `connections:view`
to list. No response carries a token.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.mcp_connection import McpConnection
from app.main import app

pytestmark = pytest.mark.anyio


def _account() -> McpConnection:
    return McpConnection(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        scope="user",
        catalog_key="google",
        purpose="account",
        name="google:ana@acme.com",
        label="ana@acme.com",
        url="https://www.googleapis.com",
        secret_key_version=1,
        auth_type="oauth",
        oauth_payload="sealed-refresh-token",
        granted_scopes=["https://www.googleapis.com/auth/drive"],
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.list_accounts = AsyncMock(return_value=[_account()])
    stub.account_start = AsyncMock(return_value="https://accounts.google.com/o/oauth2/v2/auth?x=1")
    stub.delete_account = AsyncMock(return_value=None)
    return stub


def _client(service: MagicMock, mock_redis: MagicMock, role: str):
    context = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_mcp_connection_service] = lambda: service

    @asynccontextmanager
    async def opened() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client

    return opened


@pytest.fixture
def owner(service: MagicMock, mock_redis: MagicMock) -> Iterator[Any]:
    yield _client(service, mock_redis, OrgRoleName.OWNER)
    app.dependency_overrides.clear()


@pytest.fixture
def viewer(service: MagicMock, mock_redis: MagicMock) -> Iterator[Any]:
    yield _client(service, mock_redis, OrgRoleName.VIEWER)
    app.dependency_overrides.clear()


def _url(tail: str) -> str:
    return f"{settings.API_V1_STR}{tail}"


@pytest.mark.parametrize("prefix", ["/me/connected-accounts", "/connected-accounts"])
async def test_an_account_is_listed_by_its_address_and_never_its_token(owner, prefix) -> None:
    async with owner() as client:
        response = await client.get(_url(prefix))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1 and body["items"][0]["email"] == "ana@acme.com"
    assert "sealed-refresh-token" not in response.text


@pytest.mark.parametrize(
    ("prefix", "for_organization"),
    [("/me/connected-accounts", False), ("/connected-accounts", True)],
)
async def test_connecting_and_disconnecting_reach_the_right_owner(
    owner, service, prefix, for_organization
) -> None:
    async with owner() as client:
        started = await client.post(_url(f"{prefix}/oauth/start"))
        deleted = await client.delete(_url(f"{prefix}/{uuid.uuid4()}"))
    assert started.status_code == 200
    assert started.json()["authorization_url"].startswith("https://accounts.google.com/")
    assert deleted.status_code == 204
    assert service.account_start.await_args.kwargs == {"for_organization": for_organization}
    assert service.delete_account.await_args.kwargs == {"for_organization": for_organization}


async def test_a_viewer_connects_their_own_account_but_not_the_organizations(
    viewer, service
) -> None:
    async with viewer() as client:
        mine = await client.post(_url("/me/connected-accounts/oauth/start"))
        orgs = await client.post(_url("/connected-accounts/oauth/start"))
        gone = await client.delete(_url(f"/connected-accounts/{uuid.uuid4()}"))
    assert mine.status_code == 200
    assert orgs.status_code == 403 and gone.status_code == 403
    assert service.account_start.await_count == 1
    service.delete_account.assert_not_called()
