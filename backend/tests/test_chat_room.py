"""The people with a conversation open, and the news that a turn began in it.

Redis is an in-memory stand-in: a hash per room, a list of what was published,
and a subscriber that hears what is published after it subscribed.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.clients.redis import RedisClient
from app.services import chat_room

pytestmark = pytest.mark.anyio

ROOM = "7d8a3b5e-2222-4c2a-9b1e-2f3a4b5c6d7e"


class _Store:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.published: list[tuple[str, str]] = []
        self.fail = False

    def pipeline(self) -> _Pipe:
        return _Pipe(self)

    async def hset(self, key: str, field: str, value: str) -> None:
        if self.fail:
            raise ConnectionError("redis went away")
        self.hashes.setdefault(key, {})[field] = value

    async def expire(self, key: str, _ttl: int) -> None:
        return None

    async def hdel(self, key: str, field: str) -> None:
        self.hashes.get(key, {}).pop(field, None)

    async def hash_all(self, key: str) -> dict[str, str]:
        if self.fail:
            raise ConnectionError("redis went away")
        return dict(self.hashes.get(key, {}))

    hgetall = hash_all

    async def publish(self, channel: str, data: str) -> None:
        self.published.append((channel, data))

    def pubsub(self, *, ignore_subscribe_messages: bool) -> _PubSub:
        assert ignore_subscribe_messages
        return _PubSub(self)


class _Pipe:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.ops: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        return lambda *args: self.ops.append((name, args))

    async def execute(self) -> list[Any]:
        return [await getattr(self.store, name)(*args) for name, args in self.ops]


class _PubSub:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.channel = channel

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "subscribe", "data": 1}
        for channel, data in list(self.store.published):
            if channel == self.channel:
                yield {"type": "message", "data": data}

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def store() -> Iterator[_Store]:
    store = _Store()
    client = MagicMock(spec=RedisClient)
    client.raw = store
    client.hash_all = store.hash_all
    chat_room.configure(client)
    yield store
    chat_room.configure(None)


def _kinds(store: _Store) -> list[str]:
    return [json.loads(data)["type"] for _, data in store.published]


class TestWhoIsHere:
    async def test_joining_counts_a_person_and_leaving_stops_counting_them(
        self, store: _Store
    ) -> None:
        anna, kacper = uuid4(), uuid4()
        await chat_room.join(ROOM, anna, "tab-a")
        await chat_room.join(ROOM, kacper, "tab-k")
        assert set(await chat_room.present(ROOM)) == {anna, kacper}

        await chat_room.leave(ROOM, anna, "tab-a")
        assert await chat_room.present(ROOM) == [kacper]
        # Every arrival and departure is news to the room.
        assert _kinds(store) == [chat_room.PRESENCE] * 3

    async def test_closing_one_of_two_tabs_leaves_the_person_here(self, store: _Store) -> None:
        anna = uuid4()
        await chat_room.join(ROOM, anna, "tab-1")
        await chat_room.join(ROOM, anna, "tab-2")
        assert await chat_room.present(ROOM) == [anna]

        await chat_room.leave(ROOM, anna, "tab-1")
        assert await chat_room.present(ROOM) == [anna]

        await chat_room.leave(ROOM, anna, "tab-2")
        assert await chat_room.present(ROOM) == []

    async def test_a_socket_that_stopped_saying_so_drops_out(self, store: _Store) -> None:
        """A tab that died without leaving: its last heartbeat ages out."""
        gone, here = uuid4(), uuid4()
        store.hashes[f"room:{ROOM}:here"] = {
            f"{gone}:tab": str(time.time() - chat_room.PRESENCE_TTL - 1),
            f"{here}:tab": str(time.time()),
            "not-a-person": "nor-a-time",
        }
        assert await chat_room.present(ROOM) == [here]

    async def test_redis_failing_counts_nobody_and_raises_nothing(self, store: _Store) -> None:
        store.fail = True
        await chat_room.join(ROOM, uuid4(), "tab")
        assert await chat_room.present(ROOM) == []
        assert store.published == []

    async def test_without_redis_nobody_is_here_and_nothing_is_heard(self) -> None:
        chat_room.configure(None)
        await chat_room.join(ROOM, uuid4(), "tab")
        await chat_room.leave(ROOM, uuid4(), "tab")
        await chat_room.turn_begun(ROOM, uuid4())
        assert await chat_room.present(ROOM) == []
        assert [event async for event in chat_room.events(ROOM)] == []


class TestAPageOfRooms:
    async def test_each_chat_names_who_is_in_it_in_one_round_trip(self, store: _Store) -> None:
        anna, kacper = uuid4(), uuid4()
        other = "8e9b4c6f-3333-4d3b-8c2f-3a4b5c6d7e8f"
        await chat_room.join(ROOM, anna, "tab-1")
        await chat_room.join(ROOM, anna, "tab-2")
        await chat_room.join(other, kacper, "tab")

        assert await chat_room.present_in([ROOM, other, "empty"]) == {
            ROOM: [anna],
            other: [kacper],
            "empty": [],
        }

    async def test_a_page_redis_cannot_answer_for_names_nobody(self, store: _Store) -> None:
        store.fail = True
        assert await chat_room.present_in([ROOM]) == {}

    async def test_no_page_or_no_redis_asks_nothing(self, store: _Store) -> None:
        assert await chat_room.present_in([]) == {}
        chat_room.configure(None)
        assert await chat_room.present_in([ROOM]) == {}


class TestWhatTheRoomHears:
    async def test_people_typing_and_turns_are_heard_and_nothing_else(self, store: _Store) -> None:
        anna = uuid4()
        channel = f"room:{ROOM}:events"
        await chat_room.join(ROOM, anna, "tab")
        await chat_room.typing(ROOM, anna)
        await chat_room.turn_begun(ROOM, anna)
        store.published += [(channel, "not json"), (channel, '{"type": "other"}')]
        store.published.append((f"room:{uuid4()}:events", '{"type": "presence"}'))

        heard = [event async for event in chat_room.events(ROOM)]

        assert heard == [
            {"type": chat_room.PRESENCE},
            {"type": chat_room.TYPING, "by": str(anna)},
            {"type": chat_room.TURN_BEGUN, "by": str(anna)},
        ]

    async def test_a_publish_that_fails_is_swallowed(self, store: _Store) -> None:
        with patch.object(store, "publish", side_effect=ConnectionError("gone")):
            await chat_room.turn_begun(ROOM, uuid4())
        assert store.published == []

    async def test_a_room_redis_will_not_subscribe_to_says_so(self, store: _Store) -> None:
        """Ended quietly, it read as a room with nothing more to say, and the socket
        stopped listening for good; raised, its listener tries again."""
        with (
            patch.object(_PubSub, "subscribe", side_effect=ConnectionError("gone")),
            pytest.raises(ConnectionError),
        ):
            [event async for event in chat_room.events(ROOM)]
