"""What "run now" answers, through the mounted app.

The status code is the contract this route changed, and this is the only place it
can be observed: the handler is called directly in
`tests/test_agent_trigger_routes.py`, where a `202` declared on the decorator is
invisible. It says the fire was accepted, not that it finished - the run starts
once the request's transaction commits (#658).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.agent_trigger import TriggerRead

pytestmark = pytest.mark.anyio

_AGENT_ID = uuid4()
_PREVIOUS_RUN_ID = uuid4()


@asynccontextmanager
async def _client(service: MagicMock) -> AsyncIterator[AsyncClient]:
    context = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_agent_trigger_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _trigger(trigger_id: UUID) -> TriggerRead:
    return TriggerRead(
        id=trigger_id,
        agent_id=_AGENT_ID,
        is_active=True,
        trigger_type="schedule",
        schedule_kind="interval",
        interval_seconds=300,
        prompt="summarise the day",
        next_fire_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_run_id=_PREVIOUS_RUN_ID,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def test_running_now_is_accepted_rather_than_answered_with_the_finished_run():
    trigger_id = uuid4()
    service = MagicMock(run_now=AsyncMock(return_value=_trigger(trigger_id)))
    async with _client(service) as client:
        response = await client.post(
            f"/api/v1/agents/{_AGENT_ID}/triggers/{trigger_id}/run", json={}
        )
    assert response.status_code == 202
