"""The system-agent routes, wired (#2575): one gate, and what reaches the service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.system_agent import SystemAgentList, SystemAgentRead

pytestmark = [pytest.mark.anyio, pytest.mark.security]

ROOT = f"{settings.API_V1_STR}/system-agents"
PERSON, ORG = uuid4(), uuid4()


def _read(role: str = "memory_maintenance") -> SystemAgentRead:
    return SystemAgentRead(role=role, enabled=True, spent_this_month=Decimal("0.5"))


@asynccontextmanager
async def _client(role: OrgRoleName) -> AsyncIterator[AsyncClient]:
    ctx = AuthContext(user_id=PERSON, organization_id=ORG, role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_budget_managers_read_both_roles() -> None:
    listing = SystemAgentList(items=[_read("daily_briefing"), _read()])
    with patch(
        "app.services.system_agent.SystemAgentService.overview",
        new=AsyncMock(return_value=listing),
    ):
        async with _client(OrgRoleName.OWNER) as client:
            response = await client.get(ROOT)

    assert response.status_code == 200
    assert [item["role"] for item in response.json()["items"]] == [
        "daily_briefing",
        "memory_maintenance",
    ]


async def test_a_role_is_replaced_with_what_the_caller_sent() -> None:
    update = AsyncMock(return_value=_read())
    model = uuid4()
    with patch("app.services.system_agent.SystemAgentService.update", new=update):
        async with _client(OrgRoleName.OWNER) as client:
            response = await client.put(
                f"{ROOT}/memory_maintenance",
                json={"enabled": True, "model_profile_id": str(model), "monthly_budget_usd": "5"},
            )
            negative = await client.put(
                f"{ROOT}/memory_maintenance", json={"enabled": True, "monthly_budget_usd": "-1"}
            )

    assert response.status_code == 200 and negative.status_code == 422
    assert update.await_args.args[1] == "memory_maintenance"
    body = update.await_args.args[2]
    assert body.model_profile_id == model and body.monthly_budget_usd == Decimal("5")


async def test_somebody_who_may_not_manage_budgets_sees_and_changes_nothing() -> None:
    async with _client(OrgRoleName.VIEWER) as client:
        read = await client.get(ROOT)
        write = await client.put(f"{ROOT}/memory_maintenance", json={"enabled": False})

    assert read.status_code == 403 and write.status_code == 403
