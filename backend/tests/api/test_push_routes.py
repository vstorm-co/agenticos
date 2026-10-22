"""`/push`: the key a browser subscribes with, the subscription, a test (#2097)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import NotFoundError
from app.main import app
from app.services.web_push import PushOutcome

pytestmark = pytest.mark.anyio

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc"
KEYS = {"p256dh": "BPk", "auth": "c2Vj"}


@asynccontextmanager
async def _client(push: MagicMock, user_id: UUID) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[deps.get_current_user] = lambda: MagicMock(id=user_id)
    app.dependency_overrides[deps.get_web_push_service] = lambda: push
    app.dependency_overrides[deps.get_deployment_settings_service] = lambda: MagicMock(
        effective_app_name=AsyncMock(return_value="Acme")
    )
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_a_browser_gets_the_key_subscribes_and_unsubscribes() -> None:
    user_id = uuid4()
    push = MagicMock(
        public_key=AsyncMock(return_value="BPub"), subscribe=AsyncMock(), unsubscribe=AsyncMock()
    )
    async with _client(push, user_id) as client:
        key = await client.get("/api/v1/push/key")
        subscribed = await client.post(
            "/api/v1/push/subscriptions",
            json={"endpoint": ENDPOINT, "keys": KEYS},
            headers={"User-Agent": "Chrome"},
        )
        unsubscribed = await client.delete(
            "/api/v1/push/subscriptions", params={"endpoint": ENDPOINT}
        )
    assert key.json() == {"public_key": "BPub"}
    assert (subscribed.status_code, unsubscribed.status_code) == (204, 204)
    assert push.subscribe.await_args.kwargs == {"user_agent": "Chrome"}
    assert push.subscribe.await_args.args[0] == user_id
    push.unsubscribe.assert_awaited_once_with(user_id, ENDPOINT)


async def test_an_endpoint_outside_the_push_services_is_refused() -> None:
    push = MagicMock(subscribe=AsyncMock())
    async with _client(push, uuid4()) as client:
        response = await client.post(
            "/api/v1/push/subscriptions",
            json={"endpoint": "https://internal.acme.local/hook", "keys": KEYS},
        )
    assert response.status_code == 422
    push.subscribe.assert_not_called()


async def test_a_test_reports_how_each_browser_took_it_and_404s_with_none() -> None:
    push = MagicMock(send_test=AsyncMock(return_value=PushOutcome(sent=1, gone=1, failed=0)))
    async with _client(push, uuid4()) as client:
        sent = await client.post("/api/v1/push/test")
        push.send_test.side_effect = NotFoundError(message="none")
        missing = await client.post("/api/v1/push/test")
    assert sent.json() == {"sent": 1, "gone": 1, "failed": 0}
    assert push.send_test.await_args.kwargs == {"app_name": "Acme"}
    assert missing.status_code == 404
