"""Use-only API credentials cannot reach the existing MCP management routes."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.main import app

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    ("method", "suffix", "payload"),
    [
        ("GET", "", None),
        ("POST", "", {"name": "ledger", "url": "https://ledger.example/mcp"}),
        ("PATCH", "/connection", {"label": "changed"}),
        ("DELETE", "/connection", None),
        ("POST", "/connection/test", None),
        ("GET", "/connection/calls", None),
        ("POST", "/oauth/start", {"name": "ledger", "url": "https://ledger.example/mcp"}),
    ],
)
async def test_a_use_scoped_owner_key_cannot_administer_connections(
    client: AsyncClient, method, suffix, payload
) -> None:
    caller = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=OrgRoleName.OWNER,
        key_scopes=frozenset({Perm.MCP_USE}),
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: caller
    path = suffix.replace("connection", str(uuid4()))
    response = await client.request(
        method, f"{settings.API_V1_STR}/mcp-connections{path}", json=payload
    )
    assert response.status_code == 403
