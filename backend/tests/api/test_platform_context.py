"""Connection discovery distinguishes a console session from a narrowed token."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.permissions import AuthContext
from app.main import app

pytestmark = pytest.mark.anyio


async def test_console_context_reports_no_granted_token_scopes(client: AsyncClient) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    response = await client.get("/api/v1/me/platform-context")
    assert response.status_code == 200
    body = response.json()
    assert body["authentication"] == "session" and body["granted_scopes"] is None
    assert body["organization_id"] == str(ctx.organization_id)
    assert "solution_bundles" in body["features"]
