"""The Slack app manifest route: whoever manages channels reads it (#2067)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio


async def _get(role: str) -> tuple[int, AsyncMock]:
    service = AsyncMock()
    service.slack_manifest.return_value = {"display_information": {"name": "Support"}}
    app.dependency_overrides[deps.get_org_channel_bot_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            answer = await http.get(
                f"{settings.API_V1_STR}/channels/bots/{uuid.uuid4()}/slack-manifest"
            )
    finally:
        app.dependency_overrides.clear()
    return answer.status_code, service


async def test_an_owner_reads_the_manifest() -> None:
    status, service = await _get(OrgRoleName.OWNER)

    assert status == 200
    service.slack_manifest.assert_awaited_once()


@pytest.mark.security
async def test_a_viewer_is_refused() -> None:
    status, service = await _get(OrgRoleName.VIEWER)

    assert status == 403
    service.slack_manifest.assert_not_awaited()
