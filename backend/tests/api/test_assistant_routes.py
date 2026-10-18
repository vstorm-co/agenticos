"""The assistant's routes: every member reads it, `org:settings` changes it (#2063)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.assistant import AssistantRead

pytestmark = pytest.mark.anyio

STATE = AssistantRead(
    status="ready",
    agent_id=uuid.uuid4(),
    name="AI Architect",
    greeting=None,
    can_use=False,
    can_configure=False,
)


async def test_a_viewer_reads_the_assistant() -> None:
    service = AsyncMock()
    service.state.return_value = STATE
    app.dependency_overrides[deps.get_assistant_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.VIEWER
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            answer = await http.get(f"{settings.API_V1_STR}/assistant")
    finally:
        app.dependency_overrides.clear()

    assert answer.status_code == 200
    assert answer.json()["name"] == "AI Architect"
