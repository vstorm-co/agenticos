"""A browse's live view over Redis (#2128): what it keeps, who hears it, what it takes.

Redis is replaced by an in-memory store with the same verbs - the keys, the lists
and the pub/sub channel are what the module is about, so they are asserted on
directly rather than through mock calls. Who may watch is a join against the
database and lives in `tests/integration/test_live_browse.py`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
from fastapi import WebSocketDisconnect

from app.agents.browser_events import BrowserCommand, BrowserEvent
from app.api.routes.v1.browse_live import browse_live
from app.clients.redis import RedisClient
from app.core.config import settings
from app.services import live_browse
from app.services.live_browse import BrowseMeta, LiveControl

pytestmark = pytest.mark.anyio

RUN, CALL = "run-1", "call-1"


class _PubSub:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.channel = ""
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.channel = channel

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "subscribe", "data": 1}
        for data in self.store.queued_messages:
            yield {"type": "message", "data": data}

    async def aclose(self) -> None:
        self.closed = True


class _Pipe:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.ops: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **_: self.ops.append((name, args))

    async def execute(self) -> None:
        for name, args in self.ops:
            if name == "set":
                self.store.values[args[0]] = args[1]
            elif name == "rpush":
                self.store.lists.setdefault(args[0], []).append(args[1])
            elif name == "ltrim":
                self.store.lists[args[0]] = self.store.lists[args[0]][args[1] :]
            elif name == "publish":
                self.store.published.append((args[0], args[1]))
            elif name == "expire":
                self.store.expiries.append(args[0])


class _Store:
    """Redis, in memory: values, lists, what was published and what a viewer will hear."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.published: list[tuple[str, str]] = []
        self.expiries: list[str] = []
        self.queued_messages: list[str] = []
        self.pubsubs: list[_PubSub] = []

    async def set(self, key: str, value: str, ex: int) -> None:
        assert ex == live_browse.TTL_SECONDS
        self.values[key] = value

    def pipeline(self) -> _Pipe:
        return _Pipe(self)

    def pubsub(self, *, ignore_subscribe_messages: bool) -> _PubSub:
        assert ignore_subscribe_messages
        self.pubsubs.append(_PubSub(self))
        return self.pubsubs[-1]

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def pop_left(self, key: str) -> str | None:
        items = self.lists.get(key, [])
        return items.pop(0) if items else None

    async def wait_pop_left(self, key: str, timeout: float) -> str | None:
        assert timeout > 0
        return await self.pop_left(key)

    async def list_range(self, key: str) -> list[str]:
        return list(self.lists.get(key, []))


@pytest.fixture
def store() -> Iterator[_Store]:
    store = _Store()
    client = MagicMock(spec=RedisClient)
    client.raw = store
    client.get = store.get
    client.pop_left = store.pop_left
    client.wait_pop_left = store.wait_pop_left
    client.list_range = store.list_range
    live_browse.configure(client)
    yield store
    live_browse.configure(None)


@pytest.fixture
def no_redis() -> None:
    live_browse.configure(None)


def _meta(**overrides: Any) -> BrowseMeta:
    values: dict[str, Any] = {
        "organization_id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "user_id": str(uuid.uuid4()),
        "task": "Sign in to the supplier portal",
        "started_at": datetime(2026, 10, 13, 9, 30, tzinfo=UTC),
    }
    values.update(overrides)
    return BrowseMeta(**values)


def _step(step: int = 1) -> BrowserEvent:
    return BrowserEvent(kind="browser_step", call_id=CALL, step=step, operation="CLICK")


def _frame(step: int = 1) -> BrowserEvent:
    return BrowserEvent(kind="browser_frame", call_id=CALL, step=step, image="data:,x")


def _key(part: str) -> str:
    return f"browse:{RUN}:{CALL}:{part}"


class TestWithoutRedis:
    """A CLI, a test or a deployment without Redis browses unwatched and never fails."""

    async def test_nothing_is_kept_and_nothing_is_read(self, no_redis: None) -> None:
        assert not live_browse.available()
        await live_browse.open_view(RUN, CALL, _meta())
        await live_browse.publish(RUN, CALL, _step())
        await live_browse.send(RUN, CALL, BrowserCommand(type="take_over"))

        assert await LiveControl(RUN, CALL).poll() is None
        assert await LiveControl(RUN, CALL).wait(0) is None
        assert [event async for event in live_browse.watch(RUN, CALL)] == []

    async def test_a_viewer_is_told_the_live_view_is_unavailable(self, no_redis: None) -> None:
        socket = MagicMock(close=AsyncMock())

        await live_browse.stream(socket, auth_token="t", run_id=RUN, call_id=CALL)

        socket.close.assert_awaited_once_with(code=1011, reason="Live view is unavailable")


class TestConnecting:
    async def test_a_worker_connects_once_and_keeps_its_client(
        self, monkeypatch: pytest.MonkeyPatch, no_redis: None
    ) -> None:
        """A routine's browse runs in a Prefect flow, which the API lifespan never
        configured."""
        made: list[MagicMock] = []

        def client() -> MagicMock:
            made.append(MagicMock(spec=RedisClient, connect=AsyncMock()))
            return made[-1]

        monkeypatch.setattr(live_browse, "RedisClient", client)
        try:
            await live_browse.connect_in_worker()
            await live_browse.connect_in_worker()
            assert live_browse.available()
        finally:
            live_browse.configure(None)

        assert len(made) == 1
        made[0].connect.assert_awaited_once()

    def test_the_link_is_the_console_page_of_one_browse(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://agents.example.com/")

        assert live_browse.link(RUN, CALL) == "https://agents.example.com/browse/run-1/call-1"


class TestKeeping:
    async def test_who_a_browse_belongs_to_is_kept_before_its_first_frame(
        self, store: _Store
    ) -> None:
        meta = _meta()

        await live_browse.open_view(RUN, CALL, meta)

        assert BrowseMeta.model_validate_json(store.values[_key("meta")]) == meta

    async def test_a_picture_replaces_the_last_and_is_kept_out_of_the_trace(
        self, store: _Store
    ) -> None:
        """A late viewer needs the page as it is, not a film of it."""
        await live_browse.publish(RUN, CALL, _frame(1))
        await live_browse.publish(RUN, CALL, _frame(2))

        assert BrowserEvent.model_validate_json(store.values[_key("frame")]).step == 2
        assert _key("trace") not in store.lists
        assert [channel for channel, _ in store.published] == [_key("events")] * 2

    async def test_every_other_frame_is_appended_to_a_bounded_trace(
        self, store: _Store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(live_browse, "HISTORY_LIMIT", 2)

        for step in (1, 2, 3):
            await live_browse.publish(RUN, CALL, _step(step))

        trace = [BrowserEvent.model_validate_json(item).step for item in store.lists[_key("trace")]]
        assert trace == [2, 3]
        # Each frame keeps the whole view alive, meta included, for another hour.
        assert store.expiries.count(_key("meta")) == 3

    async def test_a_failure_to_keep_or_announce_is_logged_not_raised(
        self, store: _Store, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The browse is the work; the live view is a window on it."""

        def broken(*_: Any, **__: Any) -> None:
            raise ConnectionError("redis is down")

        monkeypatch.setattr(store, "set", broken)
        monkeypatch.setattr(store, "pipeline", broken)

        await live_browse.open_view(RUN, CALL, _meta())
        await live_browse.publish(RUN, CALL, _step())

        assert "live_browse_open_failed" in caplog.text
        assert "live_browse_publish_failed" in caplog.text


class TestCommands:
    async def test_a_command_is_queued_and_read_in_order(self, store: _Store) -> None:
        await live_browse.send(RUN, CALL, BrowserCommand(type="take_over", by="Ada"))
        await live_browse.send(RUN, CALL, BrowserCommand(type="give_back"))
        control = LiveControl(RUN, CALL)

        assert await control.poll() == BrowserCommand(type="take_over", by="Ada")
        assert await control.wait(1) == BrowserCommand(type="give_back")
        assert await control.poll() is None

    async def test_an_unreadable_command_is_dropped_rather_than_stopping_the_browse(
        self, store: _Store, caplog: pytest.LogCaptureFixture
    ) -> None:
        store.lists[_key("control")] = ['{"type": "format_the_disk"}']

        assert await LiveControl(RUN, CALL).poll() is None
        assert "live_browse_command_unreadable" in caplog.text


class TestWatching:
    async def test_a_channel_hears_every_frame_but_the_pictures(self, store: _Store) -> None:
        """A channel posts words and a link, never a screenshot."""
        store.queued_messages = [
            _frame().model_dump_json(),
            "not json",
            _step(4).model_dump_json(),
        ]

        heard = [event async for event in live_browse.watch(RUN, CALL)]

        assert [(event.kind, event.step) for event in heard] == [("browser_step", 4)]
        assert store.pubsubs[0].channel == _key("events")
        assert store.pubsubs[0].closed


class _Socket:
    """An accepted viewer: what it sends, once it has seen the first live frame."""

    def __init__(self, *incoming: str) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed: tuple[int, str] | None = None
        self._incoming = list(incoming)
        self._live = anyio.Event()

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))
        if len(self.sent) == 2:
            self._live.set()

    async def receive_text(self) -> str:
        with anyio.fail_after(5):
            await self._live.wait()
        if not self._incoming:
            raise WebSocketDisconnect
        return self._incoming.pop(0)

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)


def _access(*, control: bool) -> AsyncMock:
    return AsyncMock(return_value=live_browse._Access(control=control, name="Ada Lovelace"))


class TestStreaming:
    async def test_a_browse_that_ended_long_ago_is_not_found(self, store: _Store) -> None:
        socket = _Socket()

        await live_browse.stream(socket, auth_token="t", run_id=RUN, call_id=CALL)

        assert socket.closed == (4404, "Browse not found")

    async def test_a_viewer_who_may_not_watch_is_refused_before_seeing_anything(
        self, store: _Store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await live_browse.open_view(RUN, CALL, _meta())
        monkeypatch.setattr(live_browse, "access_for", AsyncMock(return_value=None))
        socket = _Socket()

        await live_browse.stream(socket, auth_token="t", run_id=RUN, call_id=CALL)

        assert socket.closed == (4403, "Not allowed to watch")
        assert socket.sent == []

    async def test_a_late_viewer_sees_where_the_browse_is_then_follows_it(
        self, store: _Store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await live_browse.open_view(RUN, CALL, _meta())
        await live_browse.publish(RUN, CALL, _step(1))
        await live_browse.publish(RUN, CALL, _frame(1))
        store.queued_messages = [_step(2).model_dump_json()]
        monkeypatch.setattr(live_browse, "access_for", _access(control=False))
        socket = _Socket()

        await live_browse.stream(socket, auth_token="t", run_id=RUN, call_id=CALL)

        snapshot, live = socket.sent
        assert snapshot["type"] == "browser_snapshot"
        assert snapshot["task"] == "Sign in to the supplier portal"
        assert snapshot["started_at"] == "2026-10-13T09:30:00+00:00"
        assert snapshot["can_control"] is False
        assert [frame["step"] for frame in snapshot["trace"]] == [1]
        assert snapshot["frame"]["kind"] == "browser_frame"
        assert live["step"] == 2
        assert store.pubsubs[0].closed

    async def test_a_viewer_who_may_drive_has_their_commands_queued_under_their_name(
        self, store: _Store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The name is stamped here, never taken from the client - it is how the
        people watching see who has the browser."""
        await live_browse.open_view(RUN, CALL, _meta())
        store.queued_messages = [_step(1).model_dump_json()]
        monkeypatch.setattr(live_browse, "access_for", _access(control=True))
        socket = _Socket(
            "not json",
            json.dumps({"type": "take_over", "by": "Somebody Else"}),
            json.dumps({"type": "type", "text": "agent"}),
        )

        await live_browse.stream(socket, auth_token="t", run_id=RUN, call_id=CALL)

        queued = [BrowserCommand.model_validate_json(raw) for raw in store.lists[_key("control")]]
        assert queued == [
            BrowserCommand(type="take_over", by="Ada Lovelace"),
            BrowserCommand(type="type", text="agent", by="Ada Lovelace"),
        ]
        assert socket.sent[0]["can_control"] is True
        assert socket.sent[0]["frame"] is None

    @pytest.mark.security
    async def test_a_viewer_who_may_only_watch_cannot_drive(
        self, store: _Store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await live_browse.open_view(RUN, CALL, _meta())
        store.queued_messages = [_step(1).model_dump_json()]
        monkeypatch.setattr(live_browse, "access_for", _access(control=False))
        socket = _Socket(json.dumps({"type": "take_over"}))

        await live_browse.stream(socket, auth_token="t", run_id=RUN, call_id=CALL)

        assert _key("control") not in store.lists


class TestRoute:
    async def test_the_socket_is_accepted_on_the_negotiated_subprotocol_then_streamed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stream = AsyncMock()
        monkeypatch.setattr(live_browse, "stream", stream)
        socket = MagicMock()
        socket.accept = AsyncMock()
        socket.state.accept_subprotocol = "browse"
        socket.state.auth_token = "token"

        await browse_live(socket, RUN, CALL, MagicMock())

        socket.accept.assert_awaited_once_with(subprotocol="browse")
        stream.assert_awaited_once_with(socket, auth_token="token", run_id=RUN, call_id=CALL)
