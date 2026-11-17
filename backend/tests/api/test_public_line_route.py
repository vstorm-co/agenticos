"""The public-line warning is the channel managers' to read."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.channel_bot import PublicLineRead

pytestmark = pytest.mark.anyio


def _read() -> PublicLineRead:
    return PublicLineRead(
        answers_unlinked=False,
        agent_name="Front desk",
        agent_version=2,
        agent_monthly_usd=None,
        organization_monthly_usd=None,
        can_turn_on=False,
        accept_customer_files=False,
        voice="off",
        rate_limit_rpm=10,
        approval_expiry_hours=72,
        recording_max_mb=2,
        file_max_mb=5,
        reaches=[{"kind": "web", "names": ["web_fetch"], "detail": "outside_ledger"}],
        refused=["memory"],
    )


async def _get(role: str, bot_id: uuid.UUID):
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)
    service = AsyncMock()
    service.public_line.return_value = _read()
    app.dependency_overrides[deps.get_org_channel_bot_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            answer = await http.get(f"{settings.API_V1_STR}/channels/bots/{bot_id}/public-line")
    finally:
        app.dependency_overrides.clear()
    return answer, service


async def test_an_admin_reads_the_warning() -> None:
    bot_id = uuid.uuid4()

    answer, service = await _get(OrgRoleName.ADMIN, bot_id)

    assert answer.status_code == 200
    assert answer.json()["reaches"][0]["kind"] == "web"
    service.public_line.assert_awaited_once_with(bot_id)


@pytest.mark.security
async def test_a_builder_is_refused() -> None:
    answer, service = await _get(OrgRoleName.BUILDER, uuid.uuid4())

    assert answer.status_code == 403
    service.public_line.assert_not_awaited()
