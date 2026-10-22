"""`/push`: the key a browser subscribes with, the subscription, an iPhone's
token, the organization's APNs key, a test (#2097)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import NotFoundError
from app.main import app
from app.schemas.push import ApnsRead
from app.services.web_push import PushOutcome

pytestmark = pytest.mark.anyio

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc"
KEYS = {"p256dh": "BPk", "auth": "c2Vj"}


P8 = "the contents of AuthKey_KEY1234567.p8"
TOKEN = "ab" * 32


@asynccontextmanager
async def _client(
    push: MagicMock,
    user_id: UUID,
    *,
    apns: MagicMock | None = None,
    deployment: MagicMock | None = None,
    admin: bool = False,
) -> AsyncIterator[AsyncClient]:
    user = MagicMock(id=user_id, is_app_admin=admin)
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_web_push_service] = lambda: push
    app.dependency_overrides[deps.get_push_service] = lambda: push
    app.dependency_overrides[deps.get_apns_service] = lambda: apns or MagicMock()
    app.dependency_overrides[deps.get_deployment_settings_service] = lambda: (
        deployment or MagicMock(effective_app_name=AsyncMock(return_value="Acme"))
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


async def test_an_endpoint_that_is_not_https_is_refused() -> None:
    push = MagicMock(subscribe=AsyncMock())
    async with _client(push, uuid4()) as client:
        response = await client.post(
            "/api/v1/push/subscriptions",
            json={"endpoint": "http://ntfy.acme.com/up", "keys": KEYS},
        )
    assert response.status_code == 422
    push.subscribe.assert_not_called()


async def test_a_test_reports_how_each_device_took_it_and_404s_with_none() -> None:
    push = MagicMock(send_test=AsyncMock(return_value=PushOutcome(sent=1, gone=1, failed=0)))
    async with _client(push, uuid4()) as client:
        sent = await client.post("/api/v1/push/test")
        push.send_test.side_effect = NotFoundError(message="none")
        missing = await client.post("/api/v1/push/test")
    assert sent.json() == {"sent": 1, "gone": 1, "failed": 0}
    assert push.send_test.await_args.kwargs == {"app_name": "Acme"}
    assert missing.status_code == 404


READ = ApnsRead(configured=True, key_id="KEY1234567", team_id="TEAM123456", topic="com.acme.app")


async def test_anybody_reads_whether_iphones_get_push_and_registers_their_own() -> None:
    user_id = uuid4()
    apns = MagicMock(
        read=AsyncMock(return_value=READ), register=AsyncMock(), unregister=AsyncMock()
    )
    async with _client(MagicMock(), user_id, apns=apns) as client:
        read = await client.get("/api/v1/push/apns")
        registered = await client.post("/api/v1/push/apns/devices", json={"token": TOKEN})
        refused = await client.post("/api/v1/push/apns/devices", json={"token": "not-hex"})
        forgotten = await client.delete("/api/v1/push/apns/devices", params={"token": TOKEN})
    assert read.json()["configured"] is True and "private_key" not in read.json()
    assert (registered.status_code, refused.status_code, forgotten.status_code) == (204, 422, 204)
    apns.register.assert_awaited_once_with(user_id, TOKEN)
    apns.unregister.assert_awaited_once_with(user_id, TOKEN)


async def test_only_an_app_admin_sets_or_clears_the_key() -> None:
    deployment = MagicMock(
        set_apns_key=AsyncMock(return_value=READ),
        clear_apns_key=AsyncMock(return_value=ApnsRead(configured=False)),
    )
    body = {
        "key_id": "KEY1234567",
        "team_id": "TEAM123456",
        "topic": "com.acme.app",
        "private_key": P8,
    }
    async with _client(MagicMock(), uuid4(), deployment=deployment) as client:
        member = await client.put("/api/v1/push/apns", json=body)
        member_clear = await client.delete("/api/v1/push/apns")
    assert (member.status_code, member_clear.status_code) == (403, 403)
    deployment.set_apns_key.assert_not_called()
    async with _client(MagicMock(), uuid4(), deployment=deployment, admin=True) as client:
        stored = await client.put("/api/v1/push/apns", json=body)
        cleared = await client.delete("/api/v1/push/apns")
    assert stored.json()["topic"] == "com.acme.app"
    assert P8 not in stored.text
    assert cleared.json()["configured"] is False
    assert deployment.set_apns_key.await_args.kwargs["data"].private_key.get_secret_value() == P8
