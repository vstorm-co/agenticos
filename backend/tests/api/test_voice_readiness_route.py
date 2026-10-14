"""`GET /agents/{agent_id}/voice`: whether a call would start, over the wire (#54)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.main import app
from app.services.voice import VoiceReadiness

pytestmark = pytest.mark.anyio

_V1 = settings.API_V1_STR


@pytest.fixture
def wired() -> Iterator[SimpleNamespace]:
    registry = MagicMock(get=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())))
    voice = MagicMock(
        readiness=AsyncMock(
            return_value=VoiceReadiness(
                available=True,
                unavailable=None,
                transport="webrtc",
                provider="openai",
                model="gpt-realtime",
                cap_seconds=600,
                minutes_left=600,
                unavailable_capabilities=["sandbox"],
            )
        )
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=OrgRoleName.MEMBER.value,
        is_app_admin=False,
    )
    app.dependency_overrides[deps.get_agent_registry_service] = lambda: registry
    app.dependency_overrides[deps.get_voice_settings_service] = lambda: voice
    yield SimpleNamespace(registry=registry, voice=voice)
    app.dependency_overrides.clear()


async def test_an_agent_the_caller_may_not_run_answers_404(client: AsyncClient, wired):
    wired.registry.get.side_effect = NotFoundError(message="Agent not found")

    resp = await client.get(f"{_V1}/agents/{uuid.uuid4()}/voice")

    assert resp.status_code == 404
    assert wired.registry.get.call_args.kwargs["perm"] is Perm.AGENTS_RUN
    wired.voice.readiness.assert_not_awaited()


async def test_readiness_never_carries_a_key(client: AsyncClient, wired):
    resp = await client.get(f"{_V1}/agents/{uuid.uuid4()}/voice")

    assert resp.status_code == 200
    assert resp.json()["transport"] == "webrtc"
    assert "secret" not in resp.text and "sk-" not in resp.text
