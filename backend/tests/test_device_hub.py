"""Who may connect a computer to the device hub, and the hub without Redis (#2305).

The routing itself is tested against a real Redis in
`tests/integration/test_device_hub.py`.
"""

import contextlib
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import WebSocketException

from app.api.routes.v1 import device_hub as route
from app.clients.redis import RedisClient
from app.core.exceptions import AuthorizationError
from app.core.security import create_access_token
from app.services import device_hub
from app.services.device_hub import _hub

pytestmark = pytest.mark.anyio


def _session(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "user_id": uuid4(),
        "is_active": True,
        "impersonator_user_id": None,
        "app_platform": "macos",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


async def _admit(session: SimpleNamespace | None, *, user_id: Any, sid: Any, monkeypatch) -> Any:
    monkeypatch.setattr(_hub.session_repo, "get_by_id", AsyncMock(return_value=session))
    token = create_access_token(subject=str(user_id), sid=str(sid) if sid else None)
    return await device_hub.admit(MagicMock(), auth_token=token, user_id=user_id)


class TestWhoMayConnectAComputer:
    async def test_the_desktop_apps_own_session_is_admitted(self, monkeypatch) -> None:
        session = _session()

        admitted = await _admit(
            session, user_id=session.user_id, sid=session.id, monkeypatch=monkeypatch
        )

        assert admitted == (session.id, "macos")

    @pytest.mark.security
    @pytest.mark.parametrize(
        "change",
        [
            {"app_platform": None},  # a browser tab's session
            {"app_platform": "ios"},  # a phone runs nothing for an agent
            {"is_active": False},  # signed out, or disconnected from Devices
            {"impersonator_user_id": uuid4()},  # an administrator standing in
        ],
    )
    async def test_anything_but_an_open_desktop_session_of_the_callers_is_refused(
        self, monkeypatch, change: dict[str, Any]
    ) -> None:
        session = _session(**change)
        with pytest.raises(AuthorizationError, match="desktop app"):
            await _admit(session, user_id=session.user_id, sid=session.id, monkeypatch=monkeypatch)

    @pytest.mark.security
    async def test_another_persons_session_is_refused(self, monkeypatch) -> None:
        session = _session()
        with pytest.raises(AuthorizationError):
            await _admit(session, user_id=uuid4(), sid=session.id, monkeypatch=monkeypatch)

    async def test_a_token_naming_no_session_is_refused(self, monkeypatch) -> None:
        with pytest.raises(AuthorizationError):
            await _admit(None, user_id=uuid4(), sid=None, monkeypatch=monkeypatch)
        with pytest.raises(AuthorizationError):
            await device_hub.admit(MagicMock(), auth_token="not-a-jwt", user_id=uuid4())


class TestWithoutRedis:
    async def test_serving_closes_the_socket_rather_than_listing_nothing(self) -> None:
        device_hub.configure(None)
        socket = SimpleNamespace(close=AsyncMock())

        await device_hub.serve(socket, user_id=uuid4(), session_id=uuid4(), platform="macos")

        socket.close.assert_awaited_once_with(code=1011, reason="Live connections are unavailable")

    async def test_a_process_nobody_configured_connects_its_own_once(self, monkeypatch) -> None:
        """The worker: a trigger's run may need the person's computer too."""
        device_hub.configure(None)
        made: list[MagicMock] = []

        def client() -> MagicMock:
            made.append(MagicMock(spec=RedisClient, connect=AsyncMock()))
            return made[-1]

        monkeypatch.setattr(_hub, "RedisClient", client)
        try:
            first = await _hub._require()
            second = await _hub._require()
        finally:
            device_hub.configure(None)

        assert first is second is made[0]
        assert len(made) == 1
        made[0].connect.assert_awaited_once()


class TestTheSocketRoute:
    """`/ws/device` admits the desktop app's own session and hands the socket on."""

    @staticmethod
    def _socket(*, api_key: bool = False) -> MagicMock:
        socket = MagicMock()
        socket.accept = AsyncMock()
        socket.state.accept_subprotocol = "device"
        socket.state.auth_token = "token"
        socket.state.api_key_caller = MagicMock() if api_key else None
        return socket

    async def test_an_admitted_app_is_served(self, monkeypatch) -> None:
        user, session_id = MagicMock(id=uuid4()), uuid4()
        monkeypatch.setattr(
            route.device_hub, "admit", AsyncMock(return_value=(session_id, "linux"))
        )
        serve = AsyncMock()
        monkeypatch.setattr(route.device_hub, "serve", serve)
        monkeypatch.setattr(route, "get_db_context", _no_db)
        socket = self._socket()

        await route.device_socket(socket, user)

        socket.accept.assert_awaited_once_with(subprotocol="device")
        serve.assert_awaited_once_with(
            socket, user_id=user.id, session_id=session_id, platform="linux"
        )

    @pytest.mark.security
    async def test_an_api_key_or_a_browser_session_is_refused_before_accepting(
        self, monkeypatch
    ) -> None:
        with pytest.raises(WebSocketException) as refused:
            await route.device_socket(self._socket(api_key=True), MagicMock(id=uuid4()))
        assert refused.value.code == 4403

        monkeypatch.setattr(
            route.device_hub,
            "admit",
            AsyncMock(side_effect=AuthorizationError(message="Only the AgenticOS desktop app")),
        )
        monkeypatch.setattr(route, "get_db_context", _no_db)
        socket = self._socket()
        with pytest.raises(WebSocketException) as refused:
            await route.device_socket(socket, MagicMock(id=uuid4()))
        assert refused.value.code == 4403
        socket.accept.assert_not_awaited()


@contextlib.asynccontextmanager
async def _no_db() -> AsyncGenerator[MagicMock]:
    yield MagicMock()
