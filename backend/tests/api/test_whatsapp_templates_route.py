"""The WhatsApp template listing route: whoever manages channels reads it (#2076)."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.channels.whatsapp_templates import LateTemplate

pytestmark = pytest.mark.anyio


async def _get(role: str) -> tuple[int, dict, AsyncMock]:
    service = AsyncMock()
    service.whatsapp_templates.return_value = [
        LateTemplate(name="late_answer", language="en_US", body="Answer: {{1}} - thanks")
    ]
    app.dependency_overrides[deps.get_org_channel_bot_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            answer = await http.get(
                f"{settings.API_V1_STR}/channels/bots/{uuid.uuid4()}/whatsapp-templates"
            )
    finally:
        app.dependency_overrides.clear()
    return answer.status_code, answer.json(), service


async def test_an_owner_reads_the_template_list() -> None:
    status, body, service = await _get(OrgRoleName.OWNER)

    assert status == 200
    assert body == {
        "items": [{"name": "late_answer", "language": "en_US", "body": "Answer: {{1}} - thanks"}],
        "total": 1,
    }
    service.whatsapp_templates.assert_awaited_once()


@pytest.mark.security
async def test_a_member_without_channels_manage_is_refused() -> None:
    status, _, service = await _get(OrgRoleName.VIEWER)

    assert status == 403
    service.whatsapp_templates.assert_not_awaited()
