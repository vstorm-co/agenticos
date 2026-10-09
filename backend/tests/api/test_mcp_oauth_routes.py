"""The console's half of MCP OAuth: consent and connected applications (#2059)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.api_key import ApiKeyScopeCatalog
from app.schemas.oauth_server import (
    OAuthConsentAnswer,
    OAuthConsentRead,
    OAuthGrantList,
    OAuthGrantRead,
)

pytestmark = pytest.mark.anyio

V1 = settings.API_V1_STR


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.describe = AsyncMock(
        return_value=OAuthConsentRead(
            request_id=uuid.uuid4(),
            client_name="Claude Code",
            client_uri=None,
            redirect_host="127.0.0.1:33418",
            organization_id=uuid.uuid4(),
            organization_name="Acme",
            catalog=ApiKeyScopeCatalog(scopes=["agents:view"], presets=[]),
        )
    )
    stub.approve = AsyncMock(return_value=OAuthConsentAnswer(redirect_to="http://cb?code=x"))
    stub.deny = AsyncMock(
        return_value=OAuthConsentAnswer(redirect_to="http://cb?error=access_denied")
    )
    stub.list_grants = AsyncMock(
        return_value=OAuthGrantList(
            items=[
                OAuthGrantRead(
                    id=uuid.uuid4(),
                    client_name="Claude Code",
                    client_uri=None,
                    user_id=uuid.uuid4(),
                    user_email="ada@example.com",
                    scopes=["agents:view"],
                    created_at=datetime(2026, 10, 9, tzinfo=UTC),
                )
            ],
            total=1,
        )
    )
    stub.disconnect = AsyncMock()
    return stub


@pytest.fixture
def client(service: MagicMock) -> Iterator[AsyncClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_oauth_server_service] = lambda: service
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def test_consent_reads_approves_and_denies(client: AsyncClient, service: MagicMock) -> None:
    request_id = uuid.uuid4()
    async with client as http:
        read = await http.get(f"{V1}/mcp-oauth/requests/{request_id}")
        approved = await http.post(
            f"{V1}/mcp-oauth/requests/{request_id}/approve", json={"scopes": ["agents:view"]}
        )
        denied = await http.post(f"{V1}/mcp-oauth/requests/{request_id}/deny")

    assert read.json()["client_name"] == "Claude Code"
    assert approved.json()["redirect_to"] == "http://cb?code=x"
    assert denied.json()["redirect_to"].endswith("error=access_denied")
    assert service.approve.await_args.args[1] == request_id


@pytest.mark.security
async def test_an_approval_without_permissions_is_refused_at_the_edge(client: AsyncClient) -> None:
    async with client as http:
        response = await http.post(
            f"{V1}/mcp-oauth/requests/{uuid.uuid4()}/approve", json={"scopes": []}
        )

    assert response.status_code == 422


async def test_connected_applications_are_listed_and_disconnected(
    client: AsyncClient, service: MagicMock
) -> None:
    grant_id = uuid.uuid4()
    async with client as http:
        listed = await http.get(f"{V1}/mcp-oauth/grants")
        removed = await http.delete(f"{V1}/mcp-oauth/grants/{grant_id}")

    assert listed.json()["total"] == 1
    assert removed.status_code == 204
    assert service.disconnect.await_args.args[1] == grant_id
