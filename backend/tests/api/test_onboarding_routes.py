"""The start routes require the current organization and delegate writes through its service."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.onboarding import MemberStartRead, OnboardingAgent, OnboardingRead

pytestmark = pytest.mark.anyio


async def test_current_member_can_read_save_and_prepare_their_own_start(
    client: AsyncClient,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    state = OnboardingRead(
        organization_id=ctx.organization_id,
        organization_name="Acme",
        goal=None,
        dismissed=False,
        can_prepare=True,
        can_configure_model=True,
        support_email=None,
        agents=[],
        latest_conversation_id=None,
        latest_completed_at=None,
        has_result=False,
    )
    service = AsyncMock()
    service.state.return_value = state
    service.preview_member.return_value = MemberStartRead(has_common_agent=False)
    service.update.return_value = state
    service.prepare.return_value = OnboardingAgent(id=uuid4(), name="Getting started")
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_onboarding_service] = lambda: service
    assert (await client.get(f"/api/v1/me/onboarding/members/{uuid4()}")).json() == {
        "has_common_agent": False
    }
    assert (await client.get("/api/v1/me/onboarding")).json()["has_result"] is False
    assert (
        await client.patch("/api/v1/me/onboarding", json={"goal": "meeting"})
    ).status_code == 200
    response = await client.patch("/api/v1/me/onboarding", json={"current_step": "member.models"})
    assert response.status_code == 200
    assert service.update.await_args.args[0] == ctx
    assert service.update.await_args.args[1].current_step == "member.models"
    assert (
        await client.patch("/api/v1/me/onboarding", json={"current_step": "not-a-step"})
    ).status_code == 422
    assert (
        await client.patch(
            "/api/v1/me/onboarding", json={"current_step": "member.tools", "user_id": str(uuid4())}
        )
    ).status_code == 422
    response = await client.patch("/api/v1/me/onboarding", json={"completed": True})
    assert response.status_code == 200
    assert service.update.await_args.args[1].completed is True
    assert (
        await client.patch("/api/v1/me/onboarding", json={"completed": False})
    ).status_code == 422
    model = uuid4()
    assert (
        await client.post("/api/v1/me/onboarding/starter", json={"model_profile_id": str(model)})
    ).status_code == 201
    service.prepare.assert_awaited_once_with(ctx, model)
    assert (
        await client.patch("/api/v1/me/onboarding", json={"has_result": True})
    ).status_code == 422


async def test_shared_scope_route_validates_scope_and_delegates_whole_state(client):
    from app.schemas.onboarding import OnboardingScopeUpdate

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    state = OnboardingRead(
        organization_id=ctx.organization_id,
        organization_name="Acme",
        goal=None,
        dismissed=False,
        can_prepare=False,
        can_configure_model=False,
        support_email=None,
        agents=[],
        latest_conversation_id=None,
        latest_completed_at=None,
        has_result=False,
    )
    service = AsyncMock()
    service.update_scope.return_value = state
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_onboarding_service] = lambda: service
    response = await client.patch(
        "/api/v1/me/onboarding/scopes/organization", json={"completed": True}
    )
    assert response.status_code == 200
    service.update_scope.assert_awaited_once_with(
        ctx, "organization", OnboardingScopeUpdate(completed=True)
    )
    assert (await client.patch("/api/v1/me/onboarding/scopes/unknown", json={})).status_code == 422
    assert (
        await client.patch("/api/v1/me/onboarding/scopes/deployment", json={"completed": False})
    ).status_code == 422


async def test_deployment_start_works_without_organization_context(client):
    from app.db.models.user import User

    actor = User(id=uuid4(), is_active=True, is_app_admin=True)
    state = OnboardingRead(
        organization_id=None,
        organization_name=None,
        goal=None,
        dismissed=False,
        can_prepare=False,
        can_configure_model=False,
        support_email=None,
        agents=[],
        latest_conversation_id=None,
        latest_completed_at=None,
        has_result=False,
    )
    service = AsyncMock()
    service.deployment_state.return_value = service.update_deployment.return_value = state
    app.dependency_overrides[deps.get_current_user] = lambda: actor
    app.dependency_overrides[deps.get_onboarding_service] = lambda: service
    response = await client.get("/api/v1/me/onboarding/deployment")
    assert response.status_code == 200 and response.json()["organization_id"] is None
    response = await client.patch("/api/v1/me/onboarding/deployment", json={"completed": True})
    assert response.status_code == 200
    service.deployment_state.assert_awaited_once_with(actor)
    service.update_deployment.assert_awaited_once()


@pytest.mark.security
async def test_no_organization_route_still_refuses_non_app_admin(client):
    from app.db.models.user import User

    app.dependency_overrides[deps.get_current_user] = lambda: User(
        id=uuid4(), is_active=True, is_app_admin=False
    )
    service = AsyncMock()
    app.dependency_overrides[deps.get_onboarding_service] = lambda: service
    assert (await client.get("/api/v1/me/onboarding/deployment")).status_code == 403
    assert (
        await client.patch("/api/v1/me/onboarding/deployment", json={"completed": True})
    ).status_code == 403
    service.deployment_state.assert_not_awaited()
    service.update_deployment.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("surface", ["mcp", "api_key"])
async def test_no_organization_setup_refuses_keys_even_with_deployment_admin_consent(
    client, surface
):
    from fastapi import Request

    from app.db.models.organization import Organization
    from app.db.models.user import User
    from app.services.api_key import KeyCaller

    actor = User(id=uuid4(), is_active=True, is_app_admin=True)
    org = Organization(id=uuid4(), name="Demo")
    caller = KeyCaller(
        user=actor,
        organization=org,
        context=AuthContext(
            user_id=actor.id, organization_id=org.id, role="owner", is_app_admin=True
        ),
        api_key_id=uuid4(),
        prefix="test",
        surface=surface,
        deployment_admin_granted=True,
    )

    async def keyed_user(request: Request):
        request.state.api_key_caller = caller
        return actor

    state = OnboardingRead(
        organization_id=None,
        organization_name=None,
        goal=None,
        dismissed=False,
        can_prepare=False,
        can_configure_model=False,
        support_email=None,
        agents=[],
        latest_conversation_id=None,
        latest_completed_at=None,
        has_result=False,
    )
    service = AsyncMock()
    service.deployment_state.return_value = service.update_deployment.return_value = state
    app.dependency_overrides[deps.get_current_user] = keyed_user
    app.dependency_overrides[deps.get_onboarding_service] = lambda: service
    assert (await client.get("/api/v1/me/onboarding/deployment")).status_code == 403
    response = await client.patch("/api/v1/me/onboarding/deployment", json={"completed": True})
    assert response.status_code == 403
    service.deployment_state.assert_not_awaited()
    service.update_deployment.assert_not_awaited()
