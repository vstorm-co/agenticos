"""Fresh probe responses preserve the server declarations the Tools dialog displays."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.agents.mcp import McpToolInfo
from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.user import User
from app.main import app

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("personal", [True, False])
async def test_probe_responses_preserve_explicit_and_absent_read_only_annotations(
    client: AsyncClient, personal: bool
) -> None:
    user = User(id=uuid4(), email="operator@example.com", is_active=True)
    caller = AuthContext(user_id=user.id, organization_id=uuid4(), role=OrgRoleName.OWNER)
    tools = [
        McpToolInfo(
            name="search",
            description="Search records",
            input_schema={"type": "object"},
            read_only=True,
            read_only_hint=True,
        ),
        McpToolInfo(
            name="update", description="Update a record", read_only=False, read_only_hint=False
        ),
        McpToolInfo(name="unannotated", description="No declaration"),
    ]
    service = MagicMock()
    service.test = AsyncMock(return_value=(None, tools, None))
    service.test_for_org = AsyncMock(return_value=(None, tools, None))
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[deps.get_auth_context] = lambda: caller
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_mcp_connection_service] = lambda: service
    try:
        root = "/me/mcp-connections" if personal else "/mcp-connections"
        response = await client.post(f"{settings.API_V1_STR}{root}/{uuid4()}/test")
        assert response.status_code == 200, response.text
        result = response.json()["tools"]
        assert [(tool["read_only"], tool["read_only_hint"]) for tool in result] == [
            (True, True),
            (False, False),
            (False, None),
        ]
        assert result[0]["input_schema"] == {"type": "object"}
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
