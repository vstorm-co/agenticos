"""Who may connect a computer to the device hub, and the hub without Redis (#2305).

The routing itself is tested against a real Redis in
`tests/integration/test_device_hub.py`.
"""

import contextlib
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import anyio
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
        "expires_at": datetime.now(UTC) + timedelta(days=1),
        "impersonator_user_id": None,
        "app_platform": "macos",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


async def _admit(session: SimpleNamespace | None, *, user_id: Any, sid: Any, monkeypatch) -> Any:
    monkeypatch.setattr(_hub.session_repo, "get_by_id", AsyncMock(return_value=session))
    token = create_access_token(subject=str(user_id), sid=str(sid) if sid else None)
    return await device_hub.admit(MagicMock(), auth_token=token, user_id=user_id)


@pytest.mark.security
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
            {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
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


@pytest.mark.security
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


@pytest.mark.parametrize("state", ["active", "revoked", "expired", "missing"])
@pytest.mark.security
async def test_each_operation_rechecks_the_session_before_reaching_the_computer(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    row = (
        _session(
            is_active=state != "revoked",
            expires_at=datetime.now(UTC) + timedelta(days=-1 if state == "expired" else 1),
        )
        if state != "missing"
        else None
    )
    read = AsyncMock(return_value=row)
    monkeypatch.setattr(_hub, "get_db_context", _no_db)
    monkeypatch.setattr(_hub.session_repo, "get_by_id", read)
    device = _hub.Device(user_id=uuid4(), session_id=uuid4(), platform="macos")
    call = _hub.Call(id="request", op="screen.capture", args={}).model_dump_json()
    cancel = _hub.Cancel(id="request").model_dump_json()

    async def frames() -> AsyncGenerator[dict[str, str]]:
        yield {"data": call}
        yield {"data": cancel}

    inbox = MagicMock()
    inbox.listen.side_effect = frames
    redis = MagicMock()
    redis.raw.publish = AsyncMock()
    socket = MagicMock(send_text=AsyncMock(), close=AsyncMock())
    if state == "active":
        await _hub._relay(redis, inbox, socket, device)
        assert [entry.args[0] for entry in socket.send_text.await_args_list] == [call, cancel]
        socket.close.assert_not_awaited()
    else:
        with pytest.raises(_hub._Disconnected):
            await _hub._relay(redis, inbox, socket, device)
        socket.send_text.assert_not_awaited()
        socket.close.assert_awaited_once_with(code=4403, reason="This computer was disconnected")
        answer = json.loads(redis.raw.publish.call_args.args[1])
        assert answer["id"] == "request" and answer["ok"] is False
    read.assert_awaited_once()


async def test_waiting_selects_the_requested_computer_and_stops_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, selected = uuid4(), uuid4()
    device = _hub.Device(user_id=user, session_id=selected, platform="macos")
    other = _hub.Device(user_id=user, session_id=uuid4(), platform="linux")
    connected = AsyncMock(side_effect=[[device], [other], [other, device]])
    monkeypatch.setattr(_hub, "connected", connected)
    monkeypatch.setattr(_hub, "WAIT_POLL_SECONDS", 0)
    assert await _hub.wait_for(user, selected, timeout=1) is device
    assert await _hub.wait_for(user, selected, timeout=1) is device
    connected.return_value = []
    connected.side_effect = None
    assert await _hub.wait_for(user, selected, timeout=0) is None
    assert await _hub.wait_for(user, selected, timeout=0.001) is None


@pytest.mark.security
@pytest.mark.parametrize(
    "text", ["x" * 17, "ą" * 9, "😀" * 5], ids=["ascii", "two-byte", "four-byte"]
)
async def test_frame_limits_count_utf8_bytes_before_parsing(
    monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    monkeypatch.setattr(_hub, "MAX_FRAME_BYTES", 16)
    socket = MagicMock(
        receive=AsyncMock(return_value={"type": "websocket.receive", "text": text}),
        close=AsyncMock(),
    )
    redis = MagicMock()
    device = _hub.Device(user_id=uuid4(), session_id=uuid4(), platform="macos")
    await _hub._read(socket, redis, device)
    socket.close.assert_awaited_once_with(
        code=1008, reason="Frames are JSON text within the size limit"
    )
    redis.raw.publish.assert_not_called()


@pytest.mark.security
async def test_a_presence_without_a_live_socket_refuses_the_call(monkeypatch):
    session_id = uuid4()
    device = _hub.Device(user_id=uuid4(), session_id=session_id, platform="macos")
    redis = MagicMock()
    redis.get = AsyncMock(return_value=device.model_dump_json())
    redis.raw.publish = AsyncMock(return_value=0)
    pubsub = MagicMock(subscribe=AsyncMock(), aclose=AsyncMock())
    redis.raw.pubsub.return_value = pubsub
    monkeypatch.setattr(_hub, "_require", AsyncMock(return_value=redis))
    with pytest.raises(_hub.DeviceUnavailable, match="closed or offline"):
        await _hub.call(session_id, "fs.read", {}, timeout=1)
    pubsub.aclose.assert_awaited_once()


async def test_cancellation_during_dispatch_still_tells_the_app_to_stop(monkeypatch):
    device = _hub.Device(user_id=uuid4(), session_id=uuid4(), platform="linux")
    redis = MagicMock()
    redis.get = AsyncMock(return_value=device.model_dump_json())
    pubsub = MagicMock(subscribe=AsyncMock(), aclose=AsyncMock())
    redis.raw.pubsub.return_value = pubsub
    monkeypatch.setattr(_hub, "_require", AsyncMock(return_value=redis))
    frames: list[_hub.Call | _hub.Cancel] = []
    with anyio.CancelScope() as scope:

        async def publish(channel: str, message: str) -> int:
            frame = _hub._server_frame.validate_json(message)
            frames.append(frame)
            if isinstance(frame, _hub.Call):
                scope.cancel()
                await anyio.lowlevel.checkpoint()
            return 1

        redis.raw.publish = AsyncMock(side_effect=publish)
        await _hub.call(device.session_id, "shell.run", {}, timeout=30)
    assert [frame.type for frame in frames] == ["call", "cancel"]
    assert frames[0].id == frames[1].id
    pubsub.aclose.assert_awaited_once()


def _rpc_fake(monkeypatch: pytest.MonkeyPatch) -> tuple[_hub.Device, MagicMock, MagicMock]:
    device = _hub.Device(user_id=uuid4(), session_id=uuid4(), platform="linux")
    redis = MagicMock()
    redis.get = AsyncMock(return_value=device.model_dump_json())
    redis.raw.publish = AsyncMock(return_value=1)
    pubsub = MagicMock(subscribe=AsyncMock(), aclose=AsyncMock())
    redis.raw.pubsub.return_value = pubsub
    monkeypatch.setattr(_hub, "_require", AsyncMock(return_value=redis))
    return device, redis, pubsub


async def test_dispatch_timeout_sends_cancel_and_closes_the_reply_channel(monkeypatch):
    device, redis, pubsub = _rpc_fake(monkeypatch)
    frames: list[_hub.Call | _hub.Cancel] = []

    async def publish(channel: str, message: str) -> int:
        frame = _hub._server_frame.validate_json(message)
        frames.append(frame)
        if isinstance(frame, _hub.Call):
            await anyio.sleep_forever()
        return 1

    redis.raw.publish = AsyncMock(side_effect=publish)
    with pytest.raises(_hub.DeviceCallTimedOut, match="within"):
        await _hub.call(device.session_id, "shell.run", {}, timeout=0.01)
    assert [frame.type for frame in frames] == ["call", "cancel"]
    assert frames[0].id == frames[1].id
    pubsub.aclose.assert_awaited_once()


@pytest.mark.parametrize("failure", ["transport", "deadline"])
async def test_failed_cancel_delivery_preserves_the_callers_cancellation(
    monkeypatch, caplog, failure
):
    from redis.exceptions import RedisError

    device, redis, pubsub = _rpc_fake(monkeypatch)
    monkeypatch.setattr(_hub, "CLEANUP_TIMEOUT_SECONDS", 0.01)
    frames: list[str] = []
    returned = False
    with anyio.CancelScope() as scope:

        async def publish(channel: str, message: str) -> int:
            frame = _hub._server_frame.validate_json(message)
            frames.append(frame.type)
            if isinstance(frame, _hub.Call):
                scope.cancel()
                await anyio.lowlevel.checkpoint()
            elif failure == "transport":
                raise RedisError("offline")
            else:
                await anyio.sleep_forever()
            return 1

        redis.raw.publish = AsyncMock(side_effect=publish)
        await _hub.call(
            device.session_id, "shell.run", {"secret": "private-command-data"}, timeout=30
        )
        returned = True
    assert not returned and frames == ["call", "cancel"]
    assert "cancellation delivery" in caplog.text
    assert "private-command-data" not in caplog.text
    pubsub.aclose.assert_awaited_once()


async def test_cancelled_subscription_still_closes_its_partially_open_channel(monkeypatch):
    device, redis, pubsub = _rpc_fake(monkeypatch)
    with anyio.CancelScope() as scope:

        async def subscribe(channel: str) -> None:
            scope.cancel()
            await anyio.lowlevel.checkpoint()

        pubsub.subscribe = AsyncMock(side_effect=subscribe)
        await _hub.call(device.session_id, "fs.read", {}, timeout=30)
    pubsub.aclose.assert_awaited_once()
    redis.raw.publish.assert_not_awaited()


@pytest.mark.parametrize("failure", ["transport", "deadline"])
async def test_channel_cleanup_failure_keeps_the_completed_result(monkeypatch, caplog, failure):
    from redis.exceptions import RedisError

    device, redis, pubsub = _rpc_fake(monkeypatch)
    monkeypatch.setattr(_hub, "CLEANUP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        _hub,
        "_first_result",
        AsyncMock(
            return_value=_hub.Result(type="result", id="done", ok=True, value={"done": True})
        ),
    )

    async def close() -> None:
        if failure == "transport":
            raise RedisError("offline")
        await anyio.sleep_forever()

    pubsub.aclose = AsyncMock(side_effect=close)
    assert await _hub.call(device.session_id, "fs.read", {}, timeout=1) == {"done": True}
    assert "channel cleanup" in caplog.text
    pubsub.aclose.assert_awaited_once()


async def test_a_stop_during_channel_cleanup_is_not_swallowed(monkeypatch):
    device, redis, pubsub = _rpc_fake(monkeypatch)
    monkeypatch.setattr(
        _hub,
        "_first_result",
        AsyncMock(
            return_value=_hub.Result(type="result", id="done", ok=True, value={"done": True})
        ),
    )
    returned = False
    with anyio.CancelScope() as scope:

        async def close() -> None:
            scope.cancel()
            await anyio.lowlevel.checkpoint()

        pubsub.aclose = AsyncMock(side_effect=close)
        await _hub.call(device.session_id, "fs.read", {}, timeout=1)
        returned = True
    assert not returned
    redis.raw.publish.assert_awaited_once()
    pubsub.aclose.assert_awaited_once()


@pytest.mark.parametrize("phase", ["presence", "subscription"])
async def test_the_call_deadline_also_bounds_connection_setup(monkeypatch, phase):
    device, redis, pubsub = _rpc_fake(monkeypatch)

    async def blocked(*args: object, **kwargs: object) -> None:
        await anyio.sleep_forever()

    if phase == "presence":
        redis.get = AsyncMock(side_effect=blocked)
    else:
        pubsub.subscribe = AsyncMock(side_effect=blocked)
    with anyio.fail_after(1), pytest.raises(_hub.DeviceCallTimedOut):
        await _hub.call(device.session_id, "fs.read", {}, timeout=0.01)
    redis.raw.publish.assert_not_awaited()
    if phase == "presence":
        pubsub.aclose.assert_not_awaited()
    else:
        pubsub.aclose.assert_awaited_once()
