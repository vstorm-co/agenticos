"""The API key routes: wired to the right permission and status codes."""

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
from app.schemas.api_key import ApiKeyCreated, ApiKeyList, ApiKeyScopeCatalog

pytestmark = pytest.mark.anyio


def _created() -> ApiKeyCreated:
    return ApiKeyCreated(
        id=uuid.uuid4(),
        name="ci",
        prefix="aos_0123abcd",
        scopes=["agents:view"],
        user_id=uuid.uuid4(),
        issuer_email="ada@example.com",
        status="active",
        expires_at=None,
        last_used_at=None,
        revoked_at=None,
        created_at=datetime(2026, 10, 9, tzinfo=UTC),
        key="aos_0123abcdsecret",
    )


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.scope_catalog = MagicMock(return_value=ApiKeyScopeCatalog(scopes=[], presets=[]))
    stub.list_keys = AsyncMock(return_value=ApiKeyList(items=[], total=0))
    stub.create = AsyncMock(return_value=_created())
    stub.revoke = AsyncMock()
    return stub


def _client(role: str, service: MagicMock) -> Iterator[AsyncClient]:
    context = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_api_key_service] = lambda: service
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
def member(service: MagicMock) -> Iterator[AsyncClient]:
    yield from _client(OrgRoleName.MEMBER, service)


@pytest.fixture
def viewer(service: MagicMock) -> Iterator[AsyncClient]:
    yield from _client(OrgRoleName.VIEWER, service)


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/api-keys{suffix}"


async def test_a_member_lists_creates_and_revokes(member: AsyncClient) -> None:
    async with member as http:
        scopes = await http.get(_url("/scopes"))
        listed = await http.get(_url())
        created = await http.post(_url(), json={"name": "ci", "scopes": ["agents:view"]})
        revoked = await http.delete(_url(f"/{uuid.uuid4()}"))

    assert scopes.status_code == 200
    assert listed.status_code == 200
    assert created.status_code == 201
    assert created.json()["key"] == "aos_0123abcdsecret"
    assert revoked.status_code == 204


@pytest.mark.security
async def test_a_viewer_cannot_issue_a_key(viewer: AsyncClient, service: MagicMock) -> None:
    async with viewer as http:
        created = await http.post(_url(), json={"name": "ci", "scopes": ["agents:view"]})

    assert created.status_code == 403
    service.create.assert_not_called()


async def test_an_unknown_scope_is_refused_at_the_edge(member: AsyncClient) -> None:
    async with member as http:
        created = await http.post(_url(), json={"name": "ci", "scopes": ["agents:fly"]})

    assert created.status_code == 422
