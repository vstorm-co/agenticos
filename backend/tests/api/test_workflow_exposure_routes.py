"""Workflow exposure routes and the workflow-run socket, through the app (#1792).

`tests/integration/test_workflow_exposures.py` drives the real service over
HTTP; this is the wire contract with the service mocked - status codes and
what each handler hands the service - and the socket route's own plumbing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.routes.v1 import workflow_run_socket as route
from app.core.config import settings
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.workflow_exposure import (
    WebhookAdmitted,
    WebhookAnswer,
    WorkflowExposureRead,
    WorkflowExposureWithSecret,
)

pytestmark = pytest.mark.anyio

_CTX = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")


def _read(**overrides) -> dict:
    now = datetime.now(UTC)
    fields = {
        "id": uuid.uuid4(),
        "workflow_id": uuid.uuid4(),
        "workflow_version_id": uuid.uuid4(),
        "version_number": 1,
        "node_instance_id": uuid.uuid4(),
        "adapter": "webhook",
        "is_active": True,
        "execution_principal_user_id": _CTX.user_id,
        "run_input": {},
        "schedule_kind": None,
        "interval_seconds": None,
        "cron_expression": None,
        "next_fire_at": None,
        "last_fired_at": None,
        "last_run_id": None,
        "created_at": now,
        "updated_at": now,
    }
    return {**fields, **overrides}


@pytest.fixture
async def wired() -> AsyncIterator[tuple[AsyncClient, MagicMock]]:
    service = MagicMock()
    app.dependency_overrides[deps.get_workflow_exposure_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: _CTX
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, service
    app.dependency_overrides.clear()


class TestExposureRoutes:
    async def test_each_route_hands_the_service_its_workflow_and_answers_in_shape(self, wired):
        client, service = wired
        workflow_id, exposure_id = uuid.uuid4(), uuid.uuid4()
        base = f"{settings.API_V1_STR}/workflows/{workflow_id}"
        rotated = WorkflowExposureWithSecret(**_read(id=exposure_id), reveal_secret="s")
        service.get_for_workflow = AsyncMock(return_value=WorkflowExposureRead(**_read()))
        service.set_active = AsyncMock(return_value=WorkflowExposureRead(**_read(is_active=False)))
        service.rotate_secret = AsyncMock(return_value=rotated)

        read = await client.get(f"{base}/exposure")
        assert read.status_code == 200 and read.json()["adapter"] == "webhook"
        changed = await client.patch(f"{base}/exposures/{exposure_id}", json={"is_active": False})
        assert changed.json()["is_active"] is False
        secret = await client.post(f"{base}/exposures/{exposure_id}/rotate-secret")
        assert secret.json()["reveal_secret"] == "s"
        assert secret.json()["webhook_url"].endswith(f"/api/v1/workflow-webhooks/{exposure_id}")

        service.get_for_workflow.assert_awaited_once_with(_CTX, workflow_id)
        assert service.set_active.await_args.args[:3] == (_CTX, workflow_id, exposure_id)
        assert service.set_active.await_args.args[3].is_active is False

    async def test_a_workflow_with_no_exposure_answers_null(self, wired):
        client, service = wired
        service.get_for_workflow = AsyncMock(return_value=None)
        read = await client.get(f"{settings.API_V1_STR}/workflows/{uuid.uuid4()}/exposure")
        assert (read.status_code, read.json()) == (200, None)

    async def test_a_pause_without_its_flag_never_reaches_the_service(self, wired):
        client, service = wired
        service.set_active = AsyncMock()
        refused = await client.patch(
            f"{settings.API_V1_STR}/workflows/{uuid.uuid4()}/exposures/{uuid.uuid4()}", json={}
        )
        assert refused.status_code == 422
        service.set_active.assert_not_awaited()

    async def test_a_delivery_is_handed_over_as_raw_bytes_and_headers(self, wired):
        client, service = wired
        run_id = uuid.uuid4()
        service.receive_webhook = AsyncMock(
            return_value=WebhookAdmitted(run_id=run_id, duplicate=False)
        )
        exposure_id = uuid.uuid4()
        answered = await client.post(
            f"{settings.API_V1_STR}/workflow-webhooks/{exposure_id}",
            content=b'{"a": 1}',
            headers={"X-Delivery-Id": "d-1"},
        )
        assert answered.status_code == 202
        assert answered.json() == {"run_id": str(run_id), "duplicate": False}
        args = service.receive_webhook.await_args
        assert args.args == (exposure_id,)
        assert args.kwargs["body"] == b'{"a": 1}'
        assert args.kwargs["headers"]["x-delivery-id"] == "d-1"

    async def test_a_graphs_own_answer_is_the_response_itself(self, wired):
        client, service = wired
        service.receive_webhook = AsyncMock(
            return_value=WebhookAnswer(
                status_code=201, headers={"X-Lead": "accepted"}, body={"lead": 1}
            )
        )
        answered = await client.post(
            f"{settings.API_V1_STR}/workflow-webhooks/{uuid.uuid4()}", content=b"{}"
        )
        assert answered.status_code == 201
        assert answered.headers["x-lead"] == "accepted"
        assert answered.json() == {"lead": 1}


class TestTheSocketRoute:
    async def test_frames_reach_the_session_and_the_stream_stops_on_disconnect(self):
        """The handler called directly: a real handshake would start the app's
        lifespan, and what is being proved is only the loop around the session."""
        organization = MagicMock(id=uuid.uuid4())
        socket = MagicMock(
            state=MagicMock(auth_token="token", accept_subprotocol="workflow"),
            accept=AsyncMock(),
            receive_json=AsyncMock(
                side_effect=[{"type": "attach", "run_id": "r"}, WebSocketDisconnect()]
            ),
        )
        session = MagicMock(handle_frame=AsyncMock(), stop=AsyncMock())
        with patch.object(route, "WorkflowRunSocket", return_value=session) as made:
            await route.workflow_run_websocket(socket, MagicMock(), organization)

        socket.accept.assert_awaited_once_with(subprotocol="workflow")
        assert made.call_args.kwargs == {"organization_id": organization.id, "auth_token": "token"}
        session.handle_frame.assert_awaited_once_with({"type": "attach", "run_id": "r"})
        session.stop.assert_awaited_once()
