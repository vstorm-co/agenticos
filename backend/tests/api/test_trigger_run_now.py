"""What "run now" answers, through the mounted app.

The status code is the contract this route changed, and this is the only place it
can be observed: the handler is called directly in
`tests/test_agent_trigger_routes.py`, where a `202` declared on the decorator is
invisible. It says the fire was accepted, not that it finished - the run starts
once the request's transaction commits (#658).
"""

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


async def test_routine_reviews_and_revocations_keep_the_path_and_review_token():
    from app.schemas.routine_actions import RoutineActionOptions
    from app.schemas.routine_sources import RoutineSourceReview

    trigger_id, version_id = uuid4(), uuid4()
    action_review = RoutineActionOptions(can_waive=True, review_token="a" * 64, items=[])
    sources = RoutineSourceReview(
        review_token="b" * 64,
        version_id=version_id,
        current=True,
        resources=[],
        accounts=[],
        unavailable_sources=[],
    )
    service = MagicMock(
        action_options=AsyncMock(return_value=action_review),
        set_action_consents=AsyncMock(return_value=action_review),
        source_options=AsyncMock(return_value=sources),
        set_source_consents=AsyncMock(return_value=sources),
    )
    root = f"/api/v1/agents/{_AGENT_ID}/triggers/{trigger_id}"
    async with _client(service) as client:
        actions = await client.get(root + "/action-consents")
        revoked = await client.put(
            root + "/action-consents", json={"actions": [], "review_token": "a" * 64}
        )
        review = await client.get(root + "/sources")
        approved = await client.put(root + "/sources", json={"review_token": "b" * 64})
        invalid = await client.put(root + "/sources", json={"review_token": "invalid"})
    assert actions.json()["items"] == revoked.json()["items"] == []
    assert review.json()["version_id"] == str(version_id)
    assert approved.json()["current"] is True
    assert invalid.status_code == 422
    assert service.set_action_consents.await_args.args[1:3] == (_AGENT_ID, trigger_id)
    assert service.set_action_consents.await_args.args[3].actions == []
    assert service.set_source_consents.await_args.args[3].review_token == "b" * 64


async def test_attempt_history_is_typed_bounded_and_delegates_resource_access():
    from app.schemas.agent_trigger import TriggerAttemptList, TriggerAttemptRead

    trigger_id, attempt_id = uuid4(), uuid4()
    page = TriggerAttemptList(
        items=[
            TriggerAttemptRead(
                id=attempt_id,
                activation_id=uuid4(),
                status="blocked",
                stage="source_review",
                reason="platform_identity_required",
                occurred_at=datetime(2026, 11, 12, tzinfo=UTC),
            )
        ],
        total=1,
    )
    service = MagicMock(attempts=AsyncMock(return_value=page))
    root = f"/api/v1/agents/{_AGENT_ID}/triggers/{trigger_id}/attempts"
    async with _client(service) as client:
        response = await client.get(root + "?skip=10&limit=10")
        refused = await client.get(root + "?limit=101")
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == str(attempt_id)
    assert response.json()["items"][0]["reason"] == "platform_identity_required"
    assert refused.status_code == 422
    service.attempts.assert_awaited_once()
    assert service.attempts.await_args.args[1:] == (_AGENT_ID, trigger_id)
    assert service.attempts.await_args.kwargs == {"skip": 10, "limit": 10}
