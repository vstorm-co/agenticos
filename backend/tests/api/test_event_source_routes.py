"""Source routes expose write-only credentials and bounded, authenticated live ingress."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import uuid4

import anyio
import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.background import drain
from app.core.config import settings
from app.core.permissions import AuthContext, Perm
from app.db import session
from app.db.models.event_source import EventSource
from app.main import app
from app.repositories import event_source as source_repo
from app.schemas.event_source import (
    EventSourceCreated,
    EventSourceList,
    EventSourceRead,
    SourceAuth,
    SourceCapture,
    SourceListening,
    SourceUsageList,
)
from app.services import rate_limit, sharing

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
    assert (await client.get("/api/v1/event-sources?skip=2&limit=3")).status_code == 200
    service.list.assert_awaited_with(CTX, skip=2, limit=3)
    assert (await client.get("/api/v1/event-sources?limit=101")).status_code == 422
    assert (await client.post("/api/v1/event-sources", json={"name": "Hook"})).status_code == 201
    assert (await client.get(base)).json()["id"] == str(source.id)
    assert (await client.patch(base, json={"is_active": False})).status_code == 200
    assert (await client.get(base + "/usage")).json()["items"] == []
    assert (await client.post(base + "/listen")).json()["listener_id"] == "listener-id"
    samples.listen.assert_awaited_once_with(CTX, source.id)
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


@pytest.mark.security
@pytest.mark.parametrize(
    "permission, same_tenant, status",
    [
        (Perm.EVENT_SOURCES_VIEW, True, 200),
        (Perm.EVENT_SOURCES_EDIT, True, 200),
        (Perm.EVENT_SOURCES_EDIT, False, 404),
    ],
)
async def test_source_sharing_accepts_view_or_edit_scope_only_in_its_tenant(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    permission: Perm,
    same_tenant: bool,
    status: int,
) -> None:
    ctx = replace(CTX, key_scopes=frozenset({permission}))
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    row = EventSource(
        id=uuid4(),
        organization_id=ctx.organization_id if same_tenant else uuid4(),
        owner_user_id=ctx.user_id,
        visibility="private",
    )
    monkeypatch.setattr(source_repo, "get", AsyncMock(return_value=row))
    monkeypatch.setattr(
        sharing.resource_grant_repo, "list_for_resource", AsyncMock(return_value=[])
    )
    response = await client.get(f"/api/v1/event-sources/{row.id}/sharing")
    assert response.status_code == status
    if same_tenant:
        assert response.json()["visibility"] == "private"


@pytest.mark.parametrize("provider,status", [("webhook", 202), ("linear", 200)])
async def test_live_ingress_returns_provider_success_and_captures_without_second_dispatch(
    wired, provider, status
):
    client, service, samples, source = wired
    source.provider = provider
    response = await client.post(f"/api/v1/webhooks/sources/{source.id}", json={"x": 1})
    assert response.status_code == status
    service.receive.assert_awaited_once()
    samples.capture_after_commit.assert_called_once_with(
        source.id, body={"x": 1}, delivery_id="one", received_at=ANY
    )


@pytest.mark.parametrize("commit_fails", [False, True])
async def test_live_receipt_commits_and_responds_without_waiting_for_sample_cache(
    wired, mock_db_session, mock_redis, monkeypatch, commit_fails
):
    client, _, _, source = wired
    capture_started = anyio.Event()
    release_capture = anyio.Event()

    async def cache_lookup(_key):
        mock_db_session.commit.assert_awaited_once()
        capture_started.set()
        await release_capture.wait()

    @asynccontextmanager
    async def session_factory():
        yield mock_db_session

    mock_redis.get.side_effect = cache_lookup
    app.dependency_overrides.pop(deps.get_event_source_sample_service)
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    monkeypatch.setattr(session, "async_session_maker", session_factory)
    path = f"/api/v1/webhooks/sources/{source.id}"
    try:
        if commit_fails:
            mock_db_session.commit.side_effect = RuntimeError("commit failed")
            with pytest.raises(RuntimeError, match="commit failed"):
                await client.post(path, json={"x": 1})
        else:
            with anyio.fail_after(2):
                assert (await client.post(path, json={"x": 1})).status_code == 202
                await capture_started.wait()
            mock_db_session.commit.assert_awaited_once()
            mock_redis.get.assert_awaited_once_with(f"source:listeners:{source.id}")
    finally:
        release_capture.set()
        await drain()
    if commit_fails:
        mock_redis.get.assert_not_called()


async def test_oversized_ingress_is_refused_before_authentication_or_capture(wired):
    client, service, samples, source = wired
    response = await client.post(
        f"/api/v1/webhooks/sources/{source.id}",
        content=b"x" * (settings.WORKFLOW_RUN_MAX_INPUT_BYTES + 1),
    )
    assert response.status_code == 413
    service.receive.assert_not_called()
    samples.capture_after_commit.assert_not_called()


@pytest.mark.security
async def test_shared_ingress_throttles_the_address_before_reading_the_body(wired, monkeypatch):
    client, service, samples, source = wired
    over = rate_limit.Decision(allowed=False, retry_after_seconds=9)
    consume = AsyncMock(return_value=over)
    monkeypatch.setattr(rate_limit, "consume", consume)
    response = await client.post(
        f"/api/v1/webhooks/sources/{source.id}",
        content=b"x" * (settings.WORKFLOW_RUN_MAX_INPUT_BYTES + 1),
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "9"
    assert consume.await_args.kwargs["surface"] == "workflow_webhook_ip"
    assert consume.await_args.kwargs["caller"].startswith("ip:")
    service.receive.assert_not_called()
    samples.capture_after_commit.assert_not_called()
