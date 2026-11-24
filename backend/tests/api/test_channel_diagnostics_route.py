"""Readiness is an organization management operation, including for API callers."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("role,status", [(OrgRoleName.OWNER, 200), (OrgRoleName.VIEWER, 403)])
async def test_readiness_requires_channels_manage(role, status):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=role)
    service = AsyncMock()
    service.diagnostics.return_value = {
        "checks": [],
        "account_scope": "current_user",
        "credentials_probed": False,
    }
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_org_channel_bot_service] = lambda: service
    bot_id = uuid4()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            result = await client.get(f"{settings.API_V1_STR}/channels/bots/{bot_id}/diagnostics")
    finally:
        app.dependency_overrides.clear()
    assert result.status_code == status
    if status == 200:
        service.diagnostics.assert_awaited_once_with(bot_id, ctx)
    else:
        service.diagnostics.assert_not_awaited()
