"""Reaching a person's computer through the device hub, against a real Redis (#2305).

The routing is Redis's to get right - a publish nobody hears, a reply that must
not be missed, a presence that lapses - so it is tested against the real thing,
with a scripted socket standing in for the desktop app.
"""

import contextlib
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import anyio
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from app.clients.redis import RedisClient
from app.services import device_hub
from app.services.device_hub import _hub

pytestmark = pytest.mark.anyio


@pytest.fixture
async def redis() -> AsyncGenerator[RedisClient]:
    client = RedisClient()
    await client.connect()
    if not await client.ping():
        await client.close()
        pytest.skip("No Redis reachable")
    device_hub.configure(client)
    yield client
    device_hub.configure(None)
    await client.close()


@pytest.fixture(autouse=True)
def live_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _session_is(monkeypatch, active=True)


class _App:
    """The desktop app's end of the socket: frames in, frames out, and a close."""

    def __init__(self) -> None:
        self._send: MemoryObjectSendStream[dict[str, Any]]
        self._receive: MemoryObjectReceiveStream[dict[str, Any]]
        self._send, self._receive = anyio.create_memory_object_stream[dict[str, Any]](16)
        self.sent: list[dict[str, Any]] = []
        self.got_call = anyio.Event()
        self.closed: tuple[int, str] | None = None

    async def receive(self) -> dict[str, Any]:
        return await self._receive.receive()

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))
        self.got_call.set()

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = (code, reason or "")

    async def says(self, frame: dict[str, Any] | str) -> None:
        text = frame if isinstance(frame, str) else json.dumps(frame)
        await self._send.send({"type": "websocket.receive", "text": text})

    async def leaves(self) -> None:
        await self._send.send({"type": "websocket.disconnect"})


async def _connected(user_id: UUID, session_id: UUID) -> bool:
    return any(device.session_id == session_id for device in await device_hub.connected(user_id))


async def _until(check: Any) -> None:
    """Polls: what is checked is Redis's state, which signals nobody when it changes."""
    for _ in range(250):
        if await check():
            return
        await anyio.sleep(0.02)
    raise AssertionError("the condition never held")


async def test_a_call_reaches_the_app_and_its_answer_comes_back(redis: RedisClient) -> None:
    user_id, session_id, app = uuid4(), uuid4(), _App()
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(
            lambda: device_hub.serve(app, user_id=user_id, session_id=session_id, platform="macos")
        )
        await _until(lambda: _connected(user_id, session_id))
        await app.says({"type": "hello", "version": "0.3.0", "capabilities": {"screen": True}})
        await _until(lambda: _hub_says_screen(user_id, session_id))

        async def answer() -> None:
            await app.got_call.wait()
            call = app.sent[-1]
            await app.says(
                {"type": "result", "id": call["id"], "ok": True, "value": {"echo": call["args"]}}
            )

        tasks.start_soon(answer)
        value = await device_hub.call(session_id, "fs.read", {"path": "a.txt"}, timeout=5)

        assert value == {"echo": {"path": "a.txt"}}
        assert app.sent[0]["op"] == "fs.read"
        await app.says({"type": "ping"})
        await app.leaves()
    # Gone from the list as soon as the app leaves, not when the presence lapses.
    assert not await _connected(user_id, session_id)


async def _hub_says_screen(user_id: UUID, session_id: UUID) -> bool:
    devices = [d for d in await device_hub.connected(user_id) if d.session_id == session_id]
    return bool(devices) and devices[0].capabilities.screen and devices[0].version == "0.3.0"


async def test_a_computer_nobody_holds_is_unavailable_at_once(redis: RedisClient) -> None:
    with pytest.raises(device_hub.DeviceUnavailable, match="not connected"):
        await device_hub.call(uuid4(), "fs.read", {}, timeout=5)


async def test_a_refusal_comes_back_as_the_apps_own_sentence(redis: RedisClient) -> None:
    user_id, session_id, app = uuid4(), uuid4(), _App()
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(
            lambda: device_hub.serve(app, user_id=user_id, session_id=session_id, platform="linux")
        )
        await _until(lambda: _connected(user_id, session_id))

        async def refuse() -> None:
            await app.got_call.wait()
            await app.says(
                {
                    "type": "result",
                    "id": app.sent[-1]["id"],
                    "ok": False,
                    "error": "Outside the chosen folder",
                }
            )

        tasks.start_soon(refuse)
        with pytest.raises(device_hub.DeviceCallFailed, match="Outside the chosen folder"):
            await device_hub.call(session_id, "fs.write", {}, timeout=5)
        await app.leaves()


async def test_a_call_with_no_answer_times_out_and_tells_the_app_to_stop(
    redis: RedisClient,
) -> None:
    user_id, session_id, app = uuid4(), uuid4(), _App()
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(
            lambda: device_hub.serve(app, user_id=user_id, session_id=session_id, platform="linux")
        )
        await _until(lambda: _connected(user_id, session_id))

        with pytest.raises(device_hub.DeviceCallTimedOut, match="did not answer"):
            await device_hub.call(session_id, "shell.run", {}, timeout=0.3)

        await _until(lambda: _has_cancel(app))
        assert app.sent[-1]["type"] == "cancel"
        assert app.sent[-1]["id"] == app.sent[0]["id"]
        await app.leaves()


async def _has_cancel(app: _App) -> bool:
    return any(frame["type"] == "cancel" for frame in app.sent)


async def test_a_stopped_run_tells_the_app_to_stop_its_call(redis: RedisClient) -> None:
    user_id, session_id, app = uuid4(), uuid4(), _App()
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(
            lambda: device_hub.serve(app, user_id=user_id, session_id=session_id, platform="linux")
        )
        await _until(lambda: _connected(user_id, session_id))

        with anyio.CancelScope() as scope:

            async def stop_once_sent() -> None:
                await app.got_call.wait()
                scope.cancel()

            tasks.start_soon(stop_once_sent)
            await device_hub.call(session_id, "shell.run", {}, timeout=30)

        await _until(lambda: _has_cancel(app))
        await app.leaves()


@pytest.mark.parametrize("frame", ['{"type": "launch"}', "not json", "x" * (17 * 2**20)])
async def test_a_frame_the_protocol_does_not_know_closes_the_socket(
    redis: RedisClient, frame: str
) -> None:
    user_id, session_id, app = uuid4(), uuid4(), _App()
    await app.says(frame)

    await device_hub.serve(app, user_id=user_id, session_id=session_id, platform="macos")

    assert app.closed is not None and app.closed[0] == 1008
    assert not await _connected(user_id, session_id)


async def test_a_reconnect_is_not_unlisted_by_the_socket_it_replaced(redis: RedisClient) -> None:
    """The app reconnects before the old socket notices it is dead; the old one's
    goodbye must not take the new one off the list."""
    user_id, session_id = uuid4(), uuid4()
    old = _hub.Device(session_id=session_id, user_id=user_id, platform="macos", connection="old")
    new = _hub.Device(session_id=session_id, user_id=user_id, platform="macos", connection="new")
    await _hub._announce(redis, old)
    await _hub._announce(redis, new)

    await _hub._withdraw(redis, old)

    assert await _connected(user_id, session_id)
    await _hub._withdraw(redis, new)
    assert not await _connected(user_id, session_id)


async def test_a_listing_whose_presence_lapsed_is_dropped(redis: RedisClient) -> None:
    user_id, session_id = uuid4(), uuid4()
    await redis.raw.sadd(f"devicehub:user:{user_id}", str(session_id))

    assert await device_hub.connected(user_id) == []
    assert await redis.raw.smembers(f"devicehub:user:{user_id}") == set()


async def test_the_heartbeat_keeps_a_device_listed_while_its_session_is_open(
    redis: RedisClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_hub, "HEARTBEAT_SECONDS", 0.05)
    _session_is(monkeypatch, active=True)
    device = _hub.Device(session_id=uuid4(), user_id=uuid4(), platform="macos", connection="c")
    with anyio.move_on_after(0.2):
        await _hub._keep_listed(redis, device, _App())
    assert await redis.raw.ttl(f"devicehub:device:{device.session_id}") > 0
    await _hub._withdraw(redis, device)


@pytest.mark.security
async def test_a_computer_disconnected_from_devices_stops_taking_calls(
    redis: RedisClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Disconnect" on the Devices screen ends the session; the open socket is
    closed at the next heartbeat with 4403, which tells the app not to reconnect."""
    monkeypatch.setattr(_hub, "HEARTBEAT_SECONDS", 0.05)
    _session_is(monkeypatch, active=False)
    user_id, session_id, app = uuid4(), uuid4(), _App()

    with anyio.fail_after(5):
        await device_hub.serve(app, user_id=user_id, session_id=session_id, platform="macos")

    assert app.closed == (4403, "This computer was disconnected")
    assert not await _connected(user_id, session_id)


def _session_is(monkeypatch: pytest.MonkeyPatch, *, active: bool, expired: bool = False) -> None:
    @contextlib.asynccontextmanager
    async def no_db() -> AsyncGenerator[object]:
        yield object()

    monkeypatch.setattr(_hub, "get_db_context", no_db)
    monkeypatch.setattr(
        _hub.session_repo,
        "get_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                is_active=active,
                expires_at=datetime.now(UTC) + timedelta(days=-1 if expired else 1),
            )
        ),
    )
