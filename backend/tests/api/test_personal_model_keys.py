"""Personal LLM routes retain member authority and return only connection metadata."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.personal_model_key import AgentModelConnectionRead, PersonalModelKeyRead
from app.services.personal_model_key import PersonalModelKeyService

pytestmark = [pytest.mark.anyio, pytest.mark.security]
CTX = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")


@pytest.fixture
async def service() -> AsyncGenerator[AsyncMock]:
    service = AsyncMock(spec=PersonalModelKeyService)
    app.dependency_overrides[deps.get_auth_context] = lambda: CTX
    app.dependency_overrides[deps.get_personal_model_key_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.clear()


async def test_member_can_connect_replace_and_delete_without_organization_management(
    service: AsyncMock,
) -> None:
    agent_id, key_id = uuid4(), uuid4()
    status = AgentModelConnectionRead(
        personal=True, connected=True, provider="openai", model="approved"
    )
    service.status.return_value = status
    service.save.return_value = status
    service.mine.return_value = [
        PersonalModelKeyRead(id=key_id, provider="openai", endpoint="https://approved.example/v1")
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/personal-model-keys/agents/{agent_id}", json={"api_key": "private-key"}
        )
        assert response.status_code == 200 and "private-key" not in response.text
        args = service.save.call_args.args
        assert args[:2] == (CTX, agent_id) and args[2].get_secret_value() == "private-key"
        response = await client.get(f"/api/v1/personal-model-keys/agents/{agent_id}")
        assert response.status_code == 200 and response.json()["personal"]
        response = await client.get("/api/v1/personal-model-keys")
        assert response.status_code == 200
        assert set(response.json()["items"][0]) == {"id", "provider", "endpoint"}
        response = await client.delete(f"/api/v1/personal-model-keys/{key_id}")
        assert response.status_code == 204
    service.status.assert_awaited_once_with(CTX, agent_id)
    service.mine.assert_awaited_once_with(CTX)
    service.delete.assert_awaited_once_with(CTX, key_id)


async def test_empty_key_is_rejected_before_service_or_provider_use(service: AsyncMock) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/personal-model-keys/agents/{uuid4()}", json={"api_key": ""}
        )
    assert response.status_code == 422
    service.save.assert_not_awaited()
