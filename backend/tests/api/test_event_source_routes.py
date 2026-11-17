"""Source routes expose write-only credentials and bounded, authenticated live ingress."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.event_source import (
    EventSourceCreated,
    EventSourceList,
    EventSourceRead,
    SourceAuth,
    SourceCapture,
    SourceListening,
    SourceUsageList,
)

pytestmark = pytest.mark.anyio
CTX = AuthContext(organization_id=uuid4(), user_id=uuid4(), role="owner")


@pytest.fixture
async def wired():
    source = EventSourceRead(
        id=uuid4(),
        name="Hook",
        provider="webhook",
        auth=SourceAuth(),
        visibility="private",
        delivery_id_header=None,
        owner_user_id=CTX.user_id,
        is_active=True,
        can_use=True,
        can_edit=True,
        webhook_url="http://localhost/hook",
    )
    service = MagicMock()
    samples = MagicMock()
    service.get = AsyncMock(return_value=source)
    service.read = AsyncMock(return_value=source)
    service.list = AsyncMock(return_value=EventSourceList(items=[source], total=1))
    service.create = AsyncMock(return_value=EventSourceCreated(**source.model_dump()))
    service.update = AsyncMock(return_value=source)
    service.delete = AsyncMock()
    service.usage = AsyncMock(return_value=SourceUsageList(items=[], total=0))
    service.replace_credentials = AsyncMock()
    service.receive = AsyncMock(
        return_value=(source, MagicMock(body={"x": 1}, external_id="one", id=uuid4()), True)
    )
    samples.capture = AsyncMock()
    samples.listen = AsyncMock(
        return_value=SourceListening(listener_id="listener-id", expires_at=datetime.now(UTC))
    )
    samples.caught = AsyncMock(return_value=SourceCapture(state="expired"))
    app.dependency_overrides[deps.get_auth_context] = lambda: CTX
    app.dependency_overrides[deps.get_event_source_service] = lambda: service
    app.dependency_overrides[deps.get_event_source_sample_service] = lambda: samples
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, service, samples, source
    app.dependency_overrides.clear()


async def test_source_routes_use_consistent_response_shapes(wired):
    client, service, samples, source = wired
    base = f"/api/v1/event-sources/{source.id}"
    assert (await client.get("/api/v1/event-sources")).json()["total"] == 1
    assert (await client.post("/api/v1/event-sources", json={"name": "Hook"})).status_code == 201
    assert (await client.get(base)).json()["id"] == str(source.id)
    assert (await client.patch(base, json={"is_active": False})).status_code == 200
    assert (await client.get(base + "/usage")).json()["items"] == []
    assert (await client.post(base + "/listen")).json()["listener_id"] == "listener-id"
    assert (await client.get(base + "/listen/a-token")).json()["state"] == "expired"
    assert (await client.delete(base)).status_code == 204
    service.delete.assert_awaited_once_with(CTX, source.id)


@pytest.mark.security
async def test_credentials_are_write_only(wired):
    client, service, _, source = wired
    response = await client.post(
        f"/api/v1/event-sources/{source.id}/credentials", json={"secret": "do-not-echo"}
    )
    assert response.status_code == 204 and not response.content
    assert "do-not-echo" not in (await client.get(f"/api/v1/event-sources/{source.id}")).text
    assert service.replace_credentials.await_args.args[2].secret.get_secret_value() == "do-not-echo"


@pytest.mark.security
async def test_viewer_cannot_create_a_source(wired):
    client, service, _, _ = wired
    app.dependency_overrides[deps.get_auth_context] = lambda: replace(CTX, role="viewer")
    assert (await client.post("/api/v1/event-sources", json={"name": "Hook"})).status_code == 403
    service.create.assert_not_called()


@pytest.mark.parametrize("provider,status", [("webhook", 202), ("linear", 200)])
async def test_live_ingress_returns_provider_success_and_captures_without_second_dispatch(
    wired, provider, status
):
    client, service, samples, source = wired
    source.provider = provider
    response = await client.post(f"/api/v1/webhooks/sources/{source.id}", json={"x": 1})
    assert response.status_code == status
    service.receive.assert_awaited_once()
    samples.capture.assert_awaited_once_with(source.id, body={"x": 1}, delivery_id="one")


async def test_oversized_ingress_is_refused_before_authentication_or_capture(wired):
    client, service, samples, source = wired
    response = await client.post(
        f"/api/v1/webhooks/sources/{source.id}",
        content=b"x" * (settings.WORKFLOW_RUN_MAX_INPUT_BYTES + 1),
    )
    assert response.status_code == 413
    service.receive.assert_not_called()
    samples.capture.assert_not_called()
