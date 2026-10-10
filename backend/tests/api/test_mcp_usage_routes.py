"""An organization MCP server's users and its call log, through the app (#2072).

The service is replaced: what is asserted is that the list hands each row the
agents the service found for it, and that the call log answers in its shape.
The queries are covered over a real database in
`tests/integration/test_mcp_usage_and_calls.py`.
"""

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
from app.db.models.mcp_connection import McpConnection
from app.main import app
from app.schemas.mcp_connection import McpToolCallRead
from app.schemas.resource_usage import AgentUsage

pytestmark = pytest.mark.anyio

V1 = settings.API_V1_STR


@pytest.fixture
def service() -> Iterator[MagicMock]:
    fake = MagicMock()
    user = MagicMock(id=uuid.uuid4())
    context = AuthContext(user_id=user.id, organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_mcp_connection_service] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


async def test_each_server_names_the_agents_using_it(service: MagicMock) -> None:
    connection = McpConnection(
        id=uuid.uuid4(),
        scope="org",
        organization_id=uuid.uuid4(),
        name="notion",
        url="https://mcp.example.com/mcp",
        secret_key_version=1,
        is_enabled=True,
        auth_type="bearer",
        visibility="org",
        is_default=False,
        created_at=datetime.now(UTC),
    )
    writer = AgentUsage(id=uuid.uuid4(), name="Writer")
    service.list_for_org = AsyncMock(return_value=([connection], 1))
    service.used_by = AsyncMock(return_value={connection.id: [writer]})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"{V1}/mcp-connections")

    assert resp.status_code == 200
    assert resp.json()["items"][0]["used_by"] == [{"id": str(writer.id), "name": "Writer"}]


async def test_a_server_s_call_log(service: MagicMock) -> None:
    connection_id = uuid.uuid4()
    service.recent_calls = AsyncMock(
        return_value=[
            McpToolCallRead(tool="search", status="completed", started_at=datetime.now(UTC))
        ]
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"{V1}/mcp-connections/{connection_id}/calls")

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["tool"] == "search"
    assert service.recent_calls.await_args.kwargs == {"connection_id": connection_id}


@pytest.mark.parametrize(("scope", "said"), [("org", "org"), ("user", "user")])
async def test_a_finished_consent_names_the_connection_and_whose_it_is(
    service: MagicMock, scope: str, said: str
) -> None:
    """So the console can offer to add an organization's server to an agent on
    its return (#2075), and offer nothing for a member's own."""
    connection = McpConnection(id=uuid.uuid4(), scope=scope, name="notion")
    service.oauth_callback = AsyncMock(return_value=connection)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"{V1}/me/mcp-connections/oauth/callback", json={"state": "s", "code": "c"}
        )

    assert response.json() == {
        "ok": True,
        "connection_name": "notion",
        "connection_id": str(connection.id),
        "scope": said,
        "error": None,
    }
