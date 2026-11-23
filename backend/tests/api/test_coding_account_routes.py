"""Personal account routes publish metadata only and reuse the caller's identity."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.coding_account import CodingAccountRead
from app.services.coding_accounts import CodingAccountService

pytestmark = pytest.mark.anyio
CTX = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")


@pytest.fixture
async def service() -> AsyncGenerator[AsyncMock]:
    service = AsyncMock(spec=CodingAccountService)
    app.dependency_overrides[deps.get_auth_context] = lambda: CTX
    app.dependency_overrides[deps.get_coding_account_service] = lambda: service
    try:
        yield service
    finally:
        app.dependency_overrides.clear()


async def test_a_member_lists_only_account_metadata_through_the_service(service: AsyncMock) -> None:
    service.mine.return_value = [
        CodingAccountRead(
            id=uuid4(),
            harness="codex",
            label="Personal",
            secret_kind="openai_codex",
            enabled=True,
            generation=uuid4(),
        )
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/coding-accounts")
    assert response.status_code == 200
    assert set(response.json()["items"][0]) == {
        "id",
        "harness",
        "label",
        "secret_kind",
        "enabled",
        "generation",
    }
    service.mine.assert_awaited_once_with(CTX)


async def test_disconnect_keeps_the_callers_authority(service: AsyncMock) -> None:
    identifier = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/v1/coding-accounts/{identifier}")
    assert response.status_code == 204
    service.disconnect.assert_awaited_once_with(CTX, identifier)


async def test_codex_device_sign_in_finishes_without_a_pasted_address(service: AsyncMock) -> None:
    from unittest.mock import MagicMock

    from app.services.openai_codex import DeviceSignIn

    oauth = MagicMock()
    oauth.start_device_sign_in = AsyncMock(
        return_value=DeviceSignIn("state-1", "ABCD-1234", "https://auth.openai.com/codex/device", 5)
    )
    oauth.poll_device_sign_in = AsyncMock(return_value=True)
    oauth.finish_personal_sign_in = AsyncMock(return_value="sealed-later")
    service.save.return_value = CodingAccountRead(
        id=uuid4(),
        harness="codex",
        label="Personal",
        secret_kind="openai_codex",
        enabled=False,
        generation=uuid4(),
    )
    app.dependency_overrides[deps.get_openai_codex_service] = lambda: oauth
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        started = await client.post("/api/v1/coding-accounts/codex/device")
        polled = await client.post("/api/v1/coding-accounts/codex/device/state-1")
        done = await client.post(
            "/api/v1/coding-accounts/codex/complete",
            json={"label": "Personal", "device_state": "state-1"},
        )
        both = await client.post(
            "/api/v1/coding-accounts/codex/complete",
            json={"label": "Personal", "device_state": "s", "callback_url": "?code=c&state=s"},
        )
        neither = await client.post(
            "/api/v1/coding-accounts/codex/complete", json={"label": "Personal"}
        )
    assert started.json() == {
        "state": "state-1",
        "user_code": "ABCD-1234",
        "verification_url": "https://auth.openai.com/codex/device",
        "interval_seconds": 5,
    }
    assert polled.json() == {"authorized": True}
    assert done.status_code == 201
    oauth.finish_personal_sign_in.assert_awaited_once_with(CTX, None, "state-1")
    assert both.status_code == 422 and neither.status_code == 422
