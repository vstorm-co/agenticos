"""A workflow's log alert routes, through the app, with the service mocked.

`tests/integration/test_workflow_log_alerts.py` drives the real service against Postgres;
this is the wire contract: status codes, what each handler hands the service, and that no
route carries a role gate in front of the service's own access check.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.routes.v1.workflow_log_alerts import router
from app.core.config import settings
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.workflow_log_alert import WorkflowLogAlertList, WorkflowLogAlertRead

pytestmark = pytest.mark.anyio

_CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="viewer")
_BODY = {
    "name": "Mail failures",
    "outcomes": ["error"],
    "threshold": 3,
    "window_minutes": 15,
    "audience": ["admins"],
}


def _read(workflow_id: uuid.UUID, **overrides) -> WorkflowLogAlertRead:
    fields = {
        "id": uuid.uuid4(),
        "workflow_id": workflow_id,
        "name": "Mail failures",
        "outcomes": ["error"],
        "node_instance_id": None,
        "message_contains": None,
        "threshold": 3,
        "window_minutes": 15,
        "audience": ["admins"],
        "user_ids": [],
        "enabled": True,
        "last_firing": None,
        "created_at": datetime.now(UTC),
        "updated_at": None,
    }
    return WorkflowLogAlertRead(**{**fields, **overrides})


@pytest.fixture
async def wired() -> AsyncIterator[tuple[AsyncClient, MagicMock]]:
    service = MagicMock()
    app.dependency_overrides[deps.get_workflow_log_alert_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: _CTX
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, service
    app.dependency_overrides.clear()


class TestLogAlertRoutes:
    async def test_each_route_hands_the_service_its_workflow_and_answers_in_shape(self, wired):
        client, service = wired
        workflow_id, rule_id = uuid.uuid4(), uuid.uuid4()
        base = f"{settings.API_V1_STR}/workflows/{workflow_id}/log-alerts"
        service.list_rules = AsyncMock(
            return_value=WorkflowLogAlertList(items=[_read(workflow_id)])
        )
        service.create_rule = AsyncMock(return_value=_read(workflow_id))
        service.update_rule = AsyncMock(return_value=_read(workflow_id, enabled=False))
        service.delete_rule = AsyncMock(return_value=None)

        listed = await client.get(base)
        created = await client.post(base, json=_BODY)
        changed = await client.patch(f"{base}/{rule_id}", json={"enabled": False})
        removed = await client.delete(f"{base}/{rule_id}")

        assert listed.status_code == 200 and listed.json()["items"][0]["audience"] == ["admins"]
        assert created.status_code == 201 and created.json()["threshold"] == 3
        assert changed.status_code == 200 and changed.json()["enabled"] is False
        assert removed.status_code == 204
        service.list_rules.assert_awaited_once_with(_CTX, workflow_id)
        assert service.create_rule.await_args.args[:2] == (_CTX, workflow_id)
        assert service.create_rule.await_args.args[2].window_minutes == 15
        assert service.update_rule.await_args.args[:3] == (_CTX, workflow_id, rule_id)
        assert service.update_rule.await_args.args[3].model_fields_set == {"enabled"}
        service.delete_rule.assert_awaited_once_with(_CTX, workflow_id, rule_id)

    @pytest.mark.parametrize(
        "change",
        [
            {"window_minutes": 7},
            {"threshold": 0},
            {"threshold": 1001},
            {"outcomes": []},
            {"audience": []},
            {"audience": ["everyone"]},
            {"name": ""},
        ],
    )
    async def test_a_rule_outside_the_bounds_is_refused_before_the_service(self, wired, change):
        client, service = wired
        service.create_rule = AsyncMock()

        response = await client.post(
            f"{settings.API_V1_STR}/workflows/{uuid.uuid4()}/log-alerts", json={**_BODY, **change}
        )

        assert response.status_code == 422
        service.create_rule.assert_not_awaited()

    @pytest.mark.parametrize(
        "field", ["name", "outcomes", "threshold", "window_minutes", "enabled"]
    )
    async def test_a_change_cannot_null_a_field_that_must_have_a_value(self, wired, field):
        client, service = wired
        service.update_rule = AsyncMock()

        response = await client.patch(
            f"{settings.API_V1_STR}/workflows/{uuid.uuid4()}/log-alerts/{uuid.uuid4()}",
            json={field: None},
        )

        assert response.status_code == 422
        service.update_rule.assert_not_awaited()

    async def test_the_step_and_the_text_can_be_cleared(self, wired):
        client, service = wired
        workflow_id = uuid.uuid4()
        service.update_rule = AsyncMock(return_value=_read(workflow_id))

        response = await client.patch(
            f"{settings.API_V1_STR}/workflows/{workflow_id}/log-alerts/{uuid.uuid4()}",
            json={"node_instance_id": None, "message_contains": None},
        )

        assert response.status_code == 200
        change = service.update_rule.await_args.args[3]
        assert change.model_dump(exclude_unset=True) == {
            "node_instance_id": None,
            "message_contains": None,
        }

    def test_no_route_carries_a_role_gate_in_front_of_the_services_own_check(self):
        for route in router.routes:
            assert not route.dependencies, route.path  # type: ignore[attr-defined]
