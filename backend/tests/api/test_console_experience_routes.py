"""The console endpoint accepts personal preferences, not caller-selected identities."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.console_experience import (
    ChatHomeOptions,
    ChatHomeOverrides,
    ConsoleExperienceRead,
    OnboardingReminderOptions,
    OnboardingReminderOverrides,
    OnboardingReminderRead,
)

pytestmark = pytest.mark.anyio


async def test_routes_use_active_auth_and_reject_identity_and_unknown_presentation_fields(
    client: AsyncClient,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    state = ConsoleExperienceRead(
        reminders=OnboardingReminderRead(
            organization_defaults=OnboardingReminderOverrides(),
            preferences=OnboardingReminderOverrides(),
            effective=OnboardingReminderOptions(),
        ),
        availability=ChatHomeOptions(),
        organization_defaults=ChatHomeOverrides(),
        preferences=ChatHomeOverrides(),
        effective=ChatHomeOptions(),
    )
    service = AsyncMock()
    service.read.return_value = state
    service.update.return_value = state
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_console_experience_service] = lambda: service
    assert (await client.get("/api/v1/users/me/console-experience")).status_code == 200
    service.read.assert_awaited_once_with(ctx)
    response = await client.patch(
        "/api/v1/users/me/console-experience", json={"preferences": {"inbox": False}}
    )
    assert response.status_code == 200
    assert service.update.await_args.args[0] == ctx
    assert service.update.await_args.args[1].preferences.inbox is False
    for body in (
        {"user_id": str(uuid4())},
        {"organization_id": str(uuid4())},
        {"preferences": {"tools": True}},
        {"preferences": {"inbox": "false"}},
    ):
        assert (
            await client.patch("/api/v1/users/me/console-experience", json=body)
        ).status_code == 422
