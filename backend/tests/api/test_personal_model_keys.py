"""Personal LLM routes retain member authority and return only connection metadata."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch
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
    agent_id, key_id, profile_id = uuid4(), uuid4(), uuid4()
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
            f"/api/v1/personal-model-keys/agents/{agent_id}",
            json={
                "api_key": "private-key",
                "expected_destination": {
                    "profile_id": str(profile_id),
                    "provider": "openai",
                    "endpoint": "https://approved.example/v1",
                    "model": "approved",
                },
            },
        )
        assert response.status_code == 200 and "private-key" not in response.text
        args = service.save.call_args.args
        assert args[:2] == (CTX, agent_id) and args[2].api_key.get_secret_value() == "private-key"
        assert args[2].expected_destination.profile_id == profile_id
        assert args[2].expected_destination.endpoint == "https://approved.example/v1"
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
            f"/api/v1/personal-model-keys/agents/{uuid4()}",
            json={
                "api_key": "",
                "expected_destination": {
                    "profile_id": str(uuid4()),
                    "provider": "openai",
                    "endpoint": None,
                    "model": "fixed",
                },
            },
        )
    assert response.status_code == 422
    service.save.assert_not_awaited()


async def test_a_key_without_the_destination_the_person_reviewed_is_refused(
    service: AsyncMock,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/personal-model-keys/agents/{uuid4()}", json={"api_key": "private-key"}
        )
    assert response.status_code == 422
    service.save.assert_not_awaited()
    assert "private-key" not in response.text


@pytest.mark.parametrize("operation", ["list", "status", "save", "delete"])
async def test_impersonated_requests_cannot_manage_the_subjects_personal_model_keys(
    operation: str,
) -> None:
    from app.agents.audience import acting_impersonated, run_impersonated
    from app.core.audit import current_impersonator, set_impersonator

    admin_id, agent_id = uuid4(), uuid4()
    db = AsyncMock()
    service = PersonalModelKeyService(db)
    previous = current_impersonator()

    async def impersonated_auth() -> AuthContext:
        # Authentication records request impersonation before an agent run exists.
        set_impersonator(admin_id)
        assert not run_impersonated()
        return CTX

    app.dependency_overrides[deps.get_auth_context] = impersonated_auth
    app.dependency_overrides[deps.get_personal_model_key_service] = lambda: service
    method = {"list": "GET", "status": "GET", "save": "PUT", "delete": "DELETE"}[operation]
    suffix = "" if operation == "list" else f"/agents/{agent_id}"
    if operation == "delete":
        suffix = f"/{uuid4()}"
    body = {
        "api_key": "private-key",
        "expected_destination": {
            "profile_id": str(uuid4()),
            "provider": "openai",
            "endpoint": None,
            "model": "approved",
        },
    }
    try:
        with (
            acting_impersonated(False),
            patch("app.services.personal_model_key.seal_secret") as seal,
            patch("app.services.personal_model_key.unseal_secret") as unseal,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.request(
                    method,
                    f"/api/v1/personal-model-keys{suffix}",
                    json=body if operation == "save" else None,
                )
            assert response.status_code == 403
            assert "signed-in web session" in response.text
            assert "private-key" not in response.text
            seal.assert_not_called()
            unseal.assert_not_called()
            assert db.mock_calls == []
    finally:
        app.dependency_overrides.clear()
        set_impersonator(previous)


async def test_copilot_routes_keep_owner_bound_handles_out_of_urls_and_tokens_out_of_responses() -> (
    None
):
    from datetime import UTC, datetime, timedelta

    from app.clients.redis import RedisClient
    from app.schemas.personal_model_key import CopilotSignInChallenge, CopilotSignInResult
    from app.services.copilot_sign_in import CopilotSignInService

    agent_id, profile_id = uuid4(), uuid4()
    handle = "own-device-authorization-handle-long-enough"
    challenge = CopilotSignInChallenge(
        handle=handle,
        user_code="OWN-CODE",
        verification_uri="https://github.com/login/device",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        poll_after_seconds=5,
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: CTX
    app.dependency_overrides[deps.get_db_session] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_redis] = lambda: RedisClient()
    try:
        with (
            patch.object(CopilotSignInService, "start", AsyncMock(return_value=challenge)) as start,
            patch.object(
                CopilotSignInService,
                "poll",
                AsyncMock(return_value=CopilotSignInResult(status="connected")),
            ) as poll,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/api/v1/personal-model-keys/agents/{agent_id}/copilot/sign-in",
                    json={
                        "expected_destination": {
                            "profile_id": str(profile_id),
                            "provider": "github_copilot",
                            "endpoint": None,
                            "model": "plan-model",
                        }
                    },
                )
                assert response.status_code == 200
                assert set(response.json()) == {
                    "handle",
                    "user_code",
                    "verification_uri",
                    "expires_at",
                    "poll_after_seconds",
                }
                assert start.call_args.args[:2] == (CTX, agent_id)
                response = await client.post(
                    f"/api/v1/personal-model-keys/agents/{agent_id}/copilot/poll",
                    json={"handle": handle},
                )
                assert response.json() == {"status": "connected", "poll_after_seconds": 0}
                poll.assert_awaited_once_with(CTX, agent_id, handle)
                response = await client.post(
                    f"/api/v1/personal-model-keys/agents/{agent_id}/copilot/poll",
                    json={"handle": "not a handle"},
                )
                assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
