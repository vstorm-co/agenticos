"""Coming back to a turn still being written: its frames kept, and followed from another socket.

Redis is an in-memory stand-in that keeps the order that matters - a frame is
on a subscriber's channel only if it was published after the subscription - so
the seam between the replayed trace and the live channel is tested as it runs.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.clients.redis import RedisClient
from app.core.exceptions import NotFoundError
from app.services import live_turn
from tests.test_agent_session import (
    _CONVERSATION,
    _chat,
    _finished_turn,
    _message,
    _sent_events,
    _session,
)

pytestmark = pytest.mark.anyio

CONVERSATION = "7d8a3b5e-1111-4c2a-9b1e-2f3a4b5c6d7e"


class _PubSub:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.start = 0
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.channel = channel
        self.start = len(self.store.published)
        if self.store.on_subscribe is not None:
            await self.store.on_subscribe()

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "subscribe", "data": 1}
        if self.store.on_listen is not None:
            await self.store.on_listen()
        for channel, data in self.store.published[self.start :]:
            if channel == self.channel:
                yield {"type": "message", "data": data}

    async def aclose(self) -> None:
        self.closed = True


class _Pipe:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.ops: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: self.ops.append((name, args, kwargs))

    async def execute(self) -> None:
        if self.store.fail:
            raise ConnectionError("redis went away")
        for name, args, kwargs in self.ops:
            await getattr(self.store, name)(*args, **kwargs)


class _Store:
    """Redis, in memory, as much of it as a turn's trace uses."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.published: list[tuple[str, str]] = []
        self.on_subscribe: Callable[[], Any] | None = None
        self.on_listen: Callable[[], Any] | None = None
        self.fail = False

    async def incr(self, key: str) -> int:
        if self.fail:
            raise ConnectionError("redis went away")
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if self.fail:
            raise ConnectionError("redis went away")
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def eval(self, _script: str, _numkeys: int, key: str, token: str) -> int:
        """`_END_IF_OURS`: delete the marker only while it names this turn."""
        if self.fail:
            raise ConnectionError("redis went away")
        if self.values.get(key) != token:
            return 0
        del self.values[key]
        return 1

    async def delete(self, *keys: str) -> None:
        if self.fail:
            raise ConnectionError("redis went away")
        for key in keys:
            self.values.pop(key, None)
            self.lists.pop(key, None)

    async def exists(self, key: str) -> int:
        return int(key in self.values)

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def ltrim(self, key: str, start: int, _end: int) -> None:
        self.lists[key] = self.lists[key][start:]

    async def expire(self, key: str, _ttl: int) -> None:
        return None

    async def publish(self, channel: str, data: str) -> None:
        self.published.append((channel, data))

    def pipeline(self) -> _Pipe:
        return _Pipe(self)

    def pubsub(self, *, ignore_subscribe_messages: bool) -> _PubSub:
        assert ignore_subscribe_messages
        return _PubSub(self)

    async def list_range(self, key: str) -> list[str]:
        return list(self.lists.get(key, []))


@pytest.fixture
def store() -> Iterator[_Store]:
    store = _Store()
    client = MagicMock(spec=RedisClient)
    client.raw = store
    client.list_range = store.list_range
    live_turn.configure(client)
    yield store
    live_turn.configure(None)


async def _begin(conversation: str = CONVERSATION) -> live_turn.Turn:
    turn = await live_turn.begin(conversation)
    assert turn is not None
    return turn


async def _followed(conversation: str = CONVERSATION) -> list[tuple[str, Any]]:
    return [(frame["type"], frame["data"]) async for frame in live_turn.follow(conversation)]


class TestKeepingATurn:
    async def test_a_follower_gets_the_turn_from_its_start_to_its_end(self, store: _Store) -> None:
        turn = await _begin()
        await live_turn.publish(turn, "model_request_start", {})
        await live_turn.publish(turn, "text_delta", {"index": 0, "content": "Hi"})
        await live_turn.end(turn)
        # Ended, so a new follower is told there is nothing to follow.
        assert await _followed() == []

    async def test_a_frame_for_the_person_who_asked_is_not_kept(self, store: _Store) -> None:
        turn = await _begin()
        for kind in live_turn.NOT_KEPT:
            await live_turn.publish(turn, kind, {})
        assert store.lists.get(turn.key("trace"), []) == []

    async def test_a_new_turn_is_followed_from_its_own_fresh_trace(self, store: _Store) -> None:
        old = await _begin()
        await live_turn.publish(old, "text_delta", {"content": "old"})
        new = await _begin()
        await live_turn.publish(new, "text_delta", {"content": "new"})
        store.on_listen = lambda: live_turn.end(new)
        frames = await _followed()
        assert frames[0] == ("text_delta", {"content": "new"})
        assert [json.loads(raw)["seq"] for raw in store.lists[new.key("trace")]] == [1, 2]

    async def test_two_turns_in_one_conversation_keep_out_of_each_others_way(
        self, store: _Store
    ) -> None:
        """Two tabs, one conversation: the second turn neither wipes the first's
        trace, nor is ended by the first finishing while it is still running."""
        first = await _begin()
        await live_turn.publish(first, "text_delta", {"content": "first"})
        second = await _begin()
        await live_turn.publish(first, "text_delta", {"content": "still first"})
        await live_turn.end(first)

        assert await live_turn.is_live(CONVERSATION)
        first_frames = [json.loads(raw) for raw in store.lists[first.key("trace")]]
        assert [frame["data"].get("content") for frame in first_frames[:2]] == [
            "first",
            "still first",
        ]
        await live_turn.publish(second, "text_delta", {"content": "second"})
        store.on_listen = lambda: live_turn.end(second)
        assert await _followed() == [
            ("text_delta", {"content": "second"}),
            (live_turn.END, {"conversation_id": CONVERSATION}),
        ]
        assert not await live_turn.is_live(CONVERSATION)

    async def test_the_seam_between_trace_and_channel_loses_and_repeats_nothing(
        self, store: _Store
    ) -> None:
        turn = await _begin()
        await live_turn.publish(turn, "text_delta", {"content": "1"})

        async def published_while_subscribing() -> None:
            # On both the trace and the channel: read once, from the trace.
            await live_turn.publish(turn, "text_delta", {"content": "2"})

        async def published_after_the_trace_was_read() -> None:
            await live_turn.publish(turn, "text_delta", {"content": "3"})
            await live_turn.end(turn)

        store.on_subscribe = published_while_subscribing
        store.on_listen = published_after_the_trace_was_read

        frames = await _followed()

        assert [data.get("content") for kind, data in frames if kind == "text_delta"] == [
            "1",
            "2",
            "3",
        ]
        assert frames[-1] == (live_turn.END, {"conversation_id": CONVERSATION})

    async def test_a_trace_already_ended_stops_at_its_end(self, store: _Store) -> None:
        turn = await _begin()
        await live_turn.publish(turn, "text_delta", {"content": "1"})

        async def ended_while_subscribing() -> None:
            await live_turn.end(turn)

        store.on_subscribe = ended_while_subscribing
        assert [kind for kind, _ in await _followed()] == ["text_delta", live_turn.END]

    async def test_a_channel_that_closes_ends_the_follow(self, store: _Store) -> None:
        turn = await _begin()
        await live_turn.publish(turn, "text_delta", {"content": "1"})
        assert [kind for kind, _ in await _followed()] == ["text_delta"]

    async def test_what_is_not_a_frame_is_skipped(self, store: _Store) -> None:
        turn = await _begin()
        await store.rpush(turn.key("trace"), "not json")
        await store.rpush(turn.key("trace"), json.dumps({"type": "x"}))

        async def broken_then_ended() -> None:
            await store.publish(turn.key("events"), "[1]")
            await live_turn.end(turn)

        store.on_listen = broken_then_ended
        assert [kind for kind, _ in await _followed()] == [live_turn.END]

    async def test_redis_failing_never_fails_the_turn(self, store: _Store) -> None:
        store.fail = True
        # Refused at the start: the turn runs unwatched.
        assert await live_turn.begin(CONVERSATION) is None
        # Refused part-way through: frames are dropped, nothing is raised.
        turn = live_turn.Turn(CONVERSATION, "t-1")
        await live_turn.publish(turn, "text_delta", {"content": "x"})
        await live_turn.end(turn)
        assert store.lists == {}

    async def test_redis_away_reads_as_nothing_running_rather_than_failing(
        self, store: _Store
    ) -> None:
        """An attach on a socket must not take the socket down with Redis."""
        store.fail = True
        with (
            patch.object(store, "exists", AsyncMock(side_effect=ConnectionError("gone"))),
            patch.object(store, "get", AsyncMock(side_effect=ConnectionError("gone"))),
        ):
            assert await live_turn.is_live(CONVERSATION) is False
            assert await _followed() == []

    async def test_without_redis_nothing_is_kept_or_followed(self) -> None:
        live_turn.configure(None)
        assert await live_turn.begin(CONVERSATION) is None
        turn = live_turn.Turn(CONVERSATION, "t-1")
        await live_turn.publish(turn, "text_delta", {})
        await live_turn.end(turn)
        assert not await live_turn.is_live(CONVERSATION)
        assert await _followed() == []


class TestFollowingFromAnotherSocket:
    @staticmethod
    def _readable(*, found: bool = True) -> Any:
        conversations = MagicMock()
        conversations.get_conversation = AsyncMock(
            side_effect=None if found else NotFoundError(message="Conversation not found")
        )
        return patch("app.services.agent_session.ConversationService", return_value=conversations)

    @staticmethod
    def _db() -> Any:
        context = patch("app.services.agent_session.get_db_context")
        return context

    async def _attach(self, session: Any, conversation: object, *, found: bool = True) -> None:
        with self._readable(found=found), self._db() as db_context:
            db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_context.return_value.__aexit__ = AsyncMock(return_value=False)
            await session.handle_frame({"type": "attach", "conversation_id": conversation})
        if session._follower is not None:
            await session._follower

    async def test_a_person_who_comes_back_gets_the_turn_so_far_and_its_end(
        self, store: _Store
    ) -> None:
        turn = await _begin()
        await live_turn.publish(turn, "model_request_start", {})
        await live_turn.publish(turn, "text_delta", {"index": 0, "content": "Reading"})
        store.on_listen = lambda: live_turn.end(turn)
        session = _session()

        await self._attach(session, CONVERSATION)

        assert _sent_events(session) == [
            ("turn_attached", {"conversation_id": CONVERSATION}),
            ("model_request_start", {}),
            ("text_delta", {"index": 0, "content": "Reading"}),
            (live_turn.END, {"conversation_id": CONVERSATION}),
        ]

    @pytest.mark.parametrize("conversation", [None, "not-a-uuid", 7])
    async def test_nothing_to_follow_is_answered_with_nothing(
        self, store: _Store, conversation: object
    ) -> None:
        session = _session()
        await self._attach(session, conversation)
        assert _sent_events(session) == []

    async def test_a_conversation_with_no_turn_running_is_answered_with_nothing(
        self, store: _Store
    ) -> None:
        session = _session()
        await self._attach(session, CONVERSATION)
        assert _sent_events(session) == []

    async def test_a_conversation_the_person_may_not_read_is_answered_with_nothing(
        self, store: _Store
    ) -> None:
        await _begin()
        session = _session()
        await self._attach(session, CONVERSATION, found=False)
        assert _sent_events(session) == []

    async def test_a_turn_that_ends_before_the_subscription_is_still_said_to_end(
        self, store: _Store
    ) -> None:
        await _begin()
        session = _session()
        with patch.object(live_turn, "follow", side_effect=lambda _c: _nothing()):
            await self._attach(session, CONVERSATION)
        assert [kind for kind, _ in _sent_events(session)] == ["turn_attached", live_turn.END]

    async def test_a_socket_gone_mid_replay_stops_forwarding(self, store: _Store) -> None:
        turn = await _begin()
        await live_turn.publish(turn, "text_delta", {"content": "1"})
        await live_turn.publish(turn, "text_delta", {"content": "2"})
        session = _session()
        session.websocket.send_json = AsyncMock(side_effect=[None, RuntimeError("closed")])
        await self._attach(session, CONVERSATION)
        assert session.websocket.send_json.await_count == 2

    async def test_asking_something_or_leaving_stops_following(self, store: _Store) -> None:
        await _begin()
        session = _session()
        hold = asyncio.Event()

        async def waiting(_conversation: str) -> AsyncIterator[dict[str, Any]]:
            await hold.wait()
            yield {"seq": 1, "type": "text_delta", "data": {}}

        with (
            patch.object(live_turn, "follow", side_effect=waiting),
            self._readable(),
            self._db() as db_context,
        ):
            db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_context.return_value.__aexit__ = AsyncMock(return_value=False)
            await session.handle_frame({"type": "attach", "conversation_id": CONVERSATION})
            follower = session._follower
            assert follower is not None
            await session.shutdown()
            await asyncio.sleep(0)
        assert follower.cancelled()
        assert session._follower is None

    async def test_a_turn_this_socket_writes_is_kept_for_whoever_comes_back(
        self, store: _Store
    ) -> None:
        session = _session()
        with _chat(AsyncMock(return_value=_finished_turn())):
            await session.process_message(_message())

        (trace,) = [key for key in store.lists if key.startswith(f"turn:{_CONVERSATION}:")]
        frames = [json.loads(raw) for raw in store.lists[trace]]
        kept = [frame["type"] for frame in frames]
        # Who asked, and which agent answers - what a follower draws the turn by.
        assert frames[0]["data"]["sender"]["name"] == "Kacper"
        assert frames[0]["data"]["agent_id"]
        # The question first: a follower in the room has no other way to see it.
        assert kept == ["turn_prompt", "message_saved", "complete", live_turn.END]
        assert not await live_turn.is_live(_CONVERSATION)


async def _nothing() -> AsyncIterator[dict[str, Any]]:
    return
    yield {}


class TestTheRoom:
    """Several people with one conversation open: who is here, and their turns."""

    @staticmethod
    def _room(
        *, here: list[Any] | None = None, events: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        async def heard(_conversation: str) -> AsyncIterator[dict[str, Any]]:
            for event in events or []:
                yield event

        return {
            "join": AsyncMock(),
            "leave": AsyncMock(),
            "present": AsyncMock(return_value=here or []),
            "events": heard,
        }

    async def _enter(self, session: Any, conversation: object, room: dict[str, Any], **kw):
        people = {person.id: person for person in kw.pop("people", [])}
        reads = kw.pop("reads", True)
        with (
            patch.object(session, "_still_reads", AsyncMock(return_value=reads)),
            patch.multiple("app.services.agent_session.chat_room", **room),
            patch(
                "app.services.agent_session.conversation_repo.users_by_id",
                AsyncMock(return_value=people),
            ),
        ):
            await TestFollowingFromAnotherSocket()._attach(session, conversation, **kw)
            if session._room_task is not None:
                await asyncio.gather(session._room_task, return_exceptions=True)

    async def test_opening_a_chat_joins_its_room_and_says_who_is_here(self) -> None:
        session = _session()
        room = self._room(here=[session.user.id])

        await self._enter(session, CONVERSATION, room, people=[session.user])

        room["join"].assert_awaited_once_with(CONVERSATION, session.user.id)
        presence = [data for kind, data in _sent_events(session) if kind == "presence"]
        assert presence == [
            {
                "conversation_id": CONVERSATION,
                "people": [
                    {
                        "user_id": str(session.user.id),
                        "name": "Kacper",
                        "has_avatar": False,
                        "avatar_color": None,
                    }
                ],
            }
        ]

    async def test_a_turn_somebody_else_began_is_followed(self, store: _Store) -> None:
        turn = await _begin()
        await live_turn.publish(turn, "turn_prompt", {"content": "Anna asks"})
        store.on_listen = lambda: live_turn.end(turn)
        session = _session()
        # Nothing running when the chat is opened: the turn begins while it is open.
        # Heard twice - two tabs announcing - and followed once.
        begun = {"type": "turn_begun", "by": "anna"}
        room = self._room(events=[{"type": "presence"}, begun, begun])
        with patch.object(live_turn, "is_live", AsyncMock(side_effect=[False, True, True])):
            await self._enter(session, CONVERSATION, room)
        if session._follower is not None:
            await session._follower

        kinds = [kind for kind, _ in _sent_events(session)]
        assert kinds[:2] == ["turn_attached", "turn_prompt"]

    async def test_moving_to_another_chat_or_none_leaves_the_room(self) -> None:
        session = _session()
        room = self._room()
        await self._enter(session, CONVERSATION, room)
        # The same chat again: still in its room, not joined twice.
        await self._enter(session, CONVERSATION, room)
        assert room["join"].await_count == 1

        await self._enter(session, None, room)
        room["leave"].assert_awaited_once_with(CONVERSATION, session.user.id)
        assert session._room is None

    async def test_a_chat_that_cannot_be_read_leaves_the_room_it_was_in(self) -> None:
        session = _session()
        room = self._room()
        await self._enter(session, CONVERSATION, room)
        await self._enter(session, str(uuid4()), room, found=False)
        room["leave"].assert_awaited_once_with(CONVERSATION, session.user.id)

    async def test_a_socket_that_closes_leaves(self) -> None:
        session = _session()
        room = self._room()
        await self._enter(session, CONVERSATION, room)
        with patch.multiple("app.services.agent_session.chat_room", **room):
            await session.shutdown()
        room["leave"].assert_awaited_once_with(CONVERSATION, session.user.id)

    async def test_an_open_chat_keeps_saying_its_reader_is_here(self) -> None:
        session = _session()
        join = AsyncMock(side_effect=[None, asyncio.CancelledError()])
        with (
            patch("app.services.agent_session.chat_room.join", join),
            patch("app.services.agent_session.chat_room.HEARTBEAT_SECONDS", 0),
            pytest.raises(asyncio.CancelledError),
        ):
            await session._heartbeat(CONVERSATION)
        assert join.await_count == 2

    async def test_somebody_who_lost_the_chat_stops_hearing_its_room(self) -> None:
        """Asked again on each piece of news: an idle socket sends nothing that
        would re-check it, and removal must still end what it hears."""
        session = _session()
        room = self._room(events=[{"type": "turn_begun", "by": "anna"}])
        with patch.object(live_turn, "is_live", AsyncMock(return_value=False)):
            await self._enter(session, CONVERSATION, room, reads=False)
        room["leave"].assert_awaited_once_with(CONVERSATION, session.user.id)
        assert session._room is None and session._follower is None

    async def test_a_followed_turn_asks_again_and_ends_for_somebody_removed(
        self, store: _Store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.agent_session.RECHECK_SECONDS", 0)
        turn = await _begin()
        await live_turn.publish(turn, "text_delta", {"content": "secret"})
        session = _session()
        with patch.object(session, "_still_reads", AsyncMock(return_value=False)):
            await session._follow(CONVERSATION)
        assert [kind for kind, _ in _sent_events(session)] == ["turn_attached", live_turn.END]

    async def test_a_followed_turn_still_readable_goes_on(
        self, store: _Store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.agent_session.RECHECK_SECONDS", 0)
        turn = await _begin()
        await live_turn.publish(turn, "text_delta", {"content": "fine"})
        store.on_listen = lambda: live_turn.end(turn)
        session = _session()
        with patch.object(session, "_still_reads", AsyncMock(return_value=True)):
            await session._follow(CONVERSATION)
        assert [kind for kind, _ in _sent_events(session)][:2] == ["turn_attached", "text_delta"]


class TestStillReading:
    @staticmethod
    def _db() -> Any:
        context = patch("app.services.agent_session.get_db_context")
        return context

    async def _ask(self, *, member: bool, found: bool) -> bool:
        session = _session()
        conversations = MagicMock()
        conversations.get_conversation = AsyncMock(
            side_effect=None if found else NotFoundError(message="Conversation not found")
        )
        with (
            self._db() as db_context,
            patch(
                "app.services.agent_session.member_repo.get",
                AsyncMock(return_value=MagicMock() if member else None),
            ),
            patch("app.services.agent_session.ConversationService", return_value=conversations),
        ):
            db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_context.return_value.__aexit__ = AsyncMock(return_value=False)
            return await session._still_reads(CONVERSATION)

    async def test_a_member_who_may_read_it_still_does(self) -> None:
        assert await self._ask(member=True, found=True) is True

    async def test_a_former_member_does_not(self) -> None:
        assert await self._ask(member=False, found=True) is False

    async def test_a_member_who_lost_the_chat_does_not(self) -> None:
        assert await self._ask(member=True, found=False) is False
