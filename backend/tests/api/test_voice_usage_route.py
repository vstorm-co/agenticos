"""`GET /voice/usage`: call minutes, gated on `runs:view` (#54)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.voice import VoiceUsage
from app.services.voice.usage import AgentMinutes

pytestmark = pytest.mark.anyio

_ORG = uuid4()
_WINDOW = "start=2026-09-01T00:00:00Z&end=2026-10-01T00:00:00Z"


def _service() -> MagicMock:
    usage = VoiceUsage(
        start=datetime(2026, 9, 1, tzinfo=UTC),
        end=datetime(2026, 10, 1, tzinfo=UTC),
        seconds=720,
        calls=4,
        by_agent=[AgentMinutes(agent_id=uuid4(), agent_name="Support", seconds=720, calls=4)],
    )
    return MagicMock(usage=AsyncMock(return_value=usage))


@asynccontextmanager
async def _client(role: str, service: MagicMock) -> AsyncIterator[AsyncClient]:
    context = AuthContext(user_id=uuid4(), organization_id=_ORG, role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_voice_usage_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_a_caller_without_runs_view_is_refused():
    service = _service()
    async with _client(OrgRoleName.MEMBER.value, service) as client:
        response = await client.get(f"/api/v1/voice/usage?{_WINDOW}")

    assert response.status_code == 403
    service.usage.assert_not_awaited()


async def test_a_window_without_its_bounds_is_refused():
    service = _service()
    async with _client(OrgRoleName.ADMIN.value, service) as client:
        response = await client.get("/api/v1/voice/usage?start=2026-09-01T00:00:00Z")

    assert response.status_code == 422
    service.usage.assert_not_awaited()


async def test_the_window_reaches_the_service_and_the_minutes_come_back():
    service = _service()
    async with _client(OrgRoleName.ADMIN.value, service) as client:
        response = await client.get(f"/api/v1/voice/usage?{_WINDOW}")

    assert response.status_code == 200
    body = response.json()
    assert (body["seconds"], body["calls"]) == (720, 4)
    assert "monthly_minutes" not in body
    assert body["by_agent"][0]["agent_name"] == "Support"
    assert service.usage.await_args.kwargs["start"] == datetime(2026, 9, 1, tzinfo=UTC)
    assert service.usage.await_args.kwargs["end"] == datetime(2026, 10, 1, tzinfo=UTC)
