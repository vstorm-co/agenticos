"""#2130: the browser setting through the app - and never the credential in it.

`tests/api/test_platform_routes.py` proves the gates; this proves what comes back.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.browser_setting import BrowserMode, BrowserSettingRead

pytestmark = pytest.mark.anyio

_SECRET = uuid.uuid4()
_PROXY = BrowserSettingRead(
    mode=BrowserMode.PROXY, proxy_url="http://proxy.example.com:8080", secret_id=_SECRET
)


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.get = AsyncMock(return_value=_PROXY)
    stub.update = AsyncMock(return_value=_PROXY)
    return stub


@pytest.fixture
def client(service: MagicMock, mock_redis: MagicMock) -> Iterator[Any]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_browser_setting_service] = lambda: service

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


URL = f"{settings.API_V1_STR}/browser-settings"


async def test_the_setting_names_its_credential_and_never_holds_it(client: Any) -> None:
    async with client() as opened:
        response = await opened.get(URL)

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "proxy"
    assert body["secret_id"] == str(_SECRET)
    assert not {"password", "api_key", "secret", "proxy_password"} & set(body)


async def test_the_whole_setting_is_written_at_once(client: Any, service: MagicMock) -> None:
    sent = {
        "mode": "proxy",
        "proxy_url": "http://proxy.example.com:8080",
        "secret_id": str(_SECRET),
    }
    async with client() as opened:
        response = await opened.put(URL, json=sent)

    assert response.status_code == 200
    written = service.update.await_args.args[1]
    assert written.mode is BrowserMode.PROXY
    assert written.proxy_url == "http://proxy.example.com:8080"


async def test_a_language_tag_that_is_not_one_is_refused_before_the_service(
    client: Any, service: MagicMock
) -> None:
    async with client() as opened:
        response = await opened.put(URL, json={"locale": "polish please"})

    assert response.status_code == 422
    service.update.assert_not_awaited()
