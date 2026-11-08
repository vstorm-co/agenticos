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
