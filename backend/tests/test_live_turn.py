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
from app.core.exceptions import AuthenticationError, NotFoundError
from app.schemas.conversation import MessageReplyRef
from app.services import live_turn
from app.services.agent import PersistedPrompt
from app.services.agent_session import AgentSession
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
        self.expiries: dict[str, list[int]] = {}
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

    async def lrem(self, key: str, _count: int, value: str) -> int:
        if self.fail:
            raise ConnectionError("redis went away")
        kept = [item for item in self.lists.get(key, []) if item != value]
        removed = len(self.lists.get(key, [])) - len(kept)
        self.lists[key] = kept
        return removed

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

    async def expire(self, key: str, ttl: int) -> None:
        self.expiries.setdefault(key, []).append(ttl)

    async def publish(self, channel: str, data: str) -> None:
        self.published.append((channel, data))

    def pipeline(self) -> _Pipe:
        return _Pipe(self)

    def pubsub(self, *, ignore_subscribe_messages: bool) -> _PubSub:
        assert ignore_subscribe_messages
        return _PubSub(self)

    async def list_range(self, key: str) -> list[str]:
        if self.fail:
            raise ConnectionError("redis went away")
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
    """The turn running now, followed as a socket in its room follows it."""
    token = await live_turn.live_token(conversation)
    if token is None:
        return []
    return [(frame["type"], frame["data"]) async for frame in live_turn.follow(conversation, token)]


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

    async def test_a_browses_pictures_are_announced_and_never_kept(self, store: _Store) -> None:
        """A screenshot a twelfth of a second, kept, filled Redis on one long
        browse; a follower arriving mid-browse just gets the next one."""
        turn = await _begin()
        await live_turn.publish(turn, "browser_frame", {"image": "data:image/jpeg;base64,AAAA"})
        await live_turn.publish(
            turn, "text_delta", {"content": "x" * (live_turn.MAX_KEPT_BYTES + 1)}
        )
        await live_turn.publish(turn, "text_delta", {"content": "kept"})

        kept = [json.loads(raw) for raw in store.lists[turn.key("trace")]]
        assert [frame["data"].get("content") for frame in kept] == ["kept"]
        announced = [json.loads(data)["type"] for channel, data in store.published]
        assert announced == ["browser_frame", "text_delta", "text_delta"]

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

        assert await live_turn.live_token(CONVERSATION) is not None
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
        assert await live_turn.live_token(CONVERSATION) is None

    async def test_a_turn_still_writing_keeps_the_conversation_live(self, store: _Store) -> None:
        """Set only when a turn began, the list expired under a turn running past an
        hour; every frame renews it, and the frame that ends a turn does not."""
        turn = await _begin()
        live = f"turn:{CONVERSATION}:live"
        store.expiries.pop(live, None)

        await live_turn.publish(turn, "text_delta", {"content": "x"})
        assert store.expiries[live] == [live_turn.TTL_SECONDS]
        await live_turn.end(turn)
        assert store.expiries[live] == [live_turn.TTL_SECONDS]

    async def test_an_older_turn_still_running_is_followed_when_the_newer_ends(
        self, store: _Store
    ) -> None:
        """The newer turn finishing first took the conversation's one marker down,
        and the older answer, still being written, streamed to nobody."""
        older = await _begin()
        newer = await _begin()
        assert await live_turn.live_token(CONVERSATION) == newer.token

        await live_turn.end(newer)

        assert await live_turn.live_token(CONVERSATION) == older.token
        await live_turn.end(older)
        assert await live_turn.live_token(CONVERSATION) is None

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
            assert await live_turn.live_token(CONVERSATION) is None
            assert await _followed() == []

    async def test_redis_going_away_mid_follow_ends_it_quietly(self, store: _Store) -> None:
        """Raised out of the follow, it killed the follower before it could say
        the turn was over, and the reader's chat kept spinning until a reload."""
        turn = await _begin()
        await live_turn.publish(turn, "text_delta", {"content": "1"})

        async def gone() -> None:
            raise ConnectionError("Redis went away")

        store.on_listen = gone
        assert [kind for kind, _ in await _followed()] == ["text_delta"]

    async def test_without_redis_nothing_is_kept_or_followed(self) -> None:
        live_turn.configure(None)
        assert await live_turn.begin(CONVERSATION) is None
        turn = live_turn.Turn(CONVERSATION, "t-1")
        await live_turn.publish(turn, "text_delta", {})
        await live_turn.end(turn)
        assert await live_turn.live_token(CONVERSATION) is None
        assert await _followed() == []
        assert [frame async for frame in live_turn.follow(CONVERSATION, "t-1")] == []


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
        with patch.object(live_turn, "follow", side_effect=lambda _c, _t: _nothing()):
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

        async def waiting(_conversation: str, _token: str) -> AsyncIterator[dict[str, Any]]:
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

    async def test_a_reply_reaches_the_teammates_with_its_quote(self, store: _Store) -> None:
        """ "Yes, do that" means nothing without the message it answers, and a
        follower has no transcript to read it from until the turn ends."""
        session = _session()
        quote = MessageReplyRef(message_id=uuid4(), role="assistant", excerpt="Plan: A, B")
        with _chat(AsyncMock(return_value=_finished_turn())) as chat:
            chat.prompt.return_value = PersistedPrompt(
                conversation_id=_CONVERSATION, newly_created=False, reply=quote
            )
            await session.process_message(_message("yes, do that"))

        (trace,) = [
            key
            for key in store.lists
            if key.startswith(f"turn:{_CONVERSATION}:") and key.endswith(":trace")
        ]
        prompt = json.loads(store.lists[trace][0])["data"]
        assert prompt["reply_to"]["excerpt"] == "Plan: A, B"

    async def test_a_turn_this_socket_writes_is_kept_for_whoever_comes_back(
        self, store: _Store
    ) -> None:
        session = _session()
        with _chat(AsyncMock(return_value=_finished_turn())):
            await session.process_message(_message())

        (trace,) = [
            key
            for key in store.lists
            if key.startswith(f"turn:{_CONVERSATION}:") and key.endswith(":trace")
        ]
        frames = [json.loads(raw) for raw in store.lists[trace]]
        kept = [frame["type"] for frame in frames]
        # Who asked, and which agent answers - what a follower draws the turn by.
        assert frames[0]["data"]["sender"]["name"] == "Kacper"
        assert frames[0]["data"]["agent_id"]
        assert frames[0]["data"]["reply_to"] is None
        # The question first: a follower in the room has no other way to see it.
        assert kept == ["turn_prompt", "message_saved", "complete", live_turn.END]
        assert await live_turn.live_token(_CONVERSATION) is None


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

        room["join"].assert_awaited_once_with(CONVERSATION, session.user.id, session._socket)
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

    async def test_somebody_else_typing_is_said_and_this_persons_own_is_not(self) -> None:
        """Like a messenger's "Anna is typing": the others hear it, the typist does
        not hear their own, and an id that is not one is dropped."""
        session = _session()
        anna = MagicMock(
            id=uuid4(), full_name="Anna", email="anna@acme.test", avatar_url=None, avatar_color=None
        )
        room = self._room(
            events=[
                {"type": "typing", "by": str(anna.id)},
                {"type": "typing", "by": str(session.user.id)},
                {"type": "typing", "by": "not-an-id"},
                {"type": "typing", "by": str(uuid4())},
            ]
        )

        await self._enter(session, CONVERSATION, room, people=[anna])

        typing = [data for kind, data in _sent_events(session) if kind == "typing"]
        assert [entry["person"]["name"] for entry in typing] == ["Anna"]
        assert typing[0]["conversation_id"] == CONVERSATION

    async def test_a_room_whose_redis_went_away_is_listened_to_again(self, monkeypatch) -> None:
        """Left to end, the socket stayed open but deaf - no presence, no typing, no
        teammate's turn - and uncounted, until a reload."""
        monkeypatch.setattr("app.services.agent_session.ROOM_RETRY_SECONDS", 0)
        session = _session()
        anna = MagicMock(
            id=uuid4(), full_name="Anna", email="anna@acme.test", avatar_url=None, avatar_color=None
        )
        calls = 0

        async def heard(_conversation: str) -> AsyncIterator[dict[str, Any]]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("Redis went away")
            yield {"type": "typing", "by": str(anna.id)}

        room = self._room()
        room["events"] = heard
        await self._enter(session, CONVERSATION, room, people=[anna])

        typing = [data for kind, data in _sent_events(session) if kind == "typing"]
        assert [entry["person"]["name"] for entry in typing] == ["Anna"]
        # Back in the room's count, as on entering it.
        assert room["join"].await_count == 2

    async def test_access_lost_while_redis_was_away_keeps_the_socket_out(self, monkeypatch) -> None:
        """Rejoining shows who is here at once, so it is asked again first."""
        monkeypatch.setattr("app.services.agent_session.ROOM_RETRY_SECONDS", 0)
        session = _session()

        async def gone(_conversation: str) -> AsyncIterator[dict[str, Any]]:
            raise ConnectionError("Redis went away")
            yield {}

        room = self._room()
        room["events"] = gone
        await self._enter(session, CONVERSATION, room, reads=False)

        assert room["join"].await_count == 1
        room["leave"].assert_awaited_once_with(CONVERSATION, session.user.id, session._socket)
        assert session._room is None

    async def test_a_typing_frame_reaches_only_the_room_this_socket_is_in(self) -> None:
        session = _session()
        with patch("app.services.agent_session.chat_room.typing", AsyncMock()) as typed:
            await session.handle_frame({"type": "typing"})
            typed.assert_not_awaited()
            session._room = CONVERSATION
            await session.handle_frame({"type": "typing"})
        typed.assert_awaited_once_with(CONVERSATION, session.user.id)

    async def test_a_stream_of_typing_frames_is_announced_once_a_while(self) -> None:
        """A client sending a frame per keystroke - or a loop - cannot make the
        room look up who is typing any faster than the console would."""
        session = _session()
        session._room = CONVERSATION
        clock = iter([100.0, 100.5, 101.9, 102.1])
        with (
            patch("app.services.agent_session.time.monotonic", lambda: next(clock)),
            patch("app.services.agent_session.chat_room.typing", AsyncMock()) as typed,
        ):
            for _ in range(4):
                await session.handle_frame({"type": "typing"})
        assert typed.await_count == 2

    async def test_a_turn_somebody_else_began_is_followed(self, store: _Store) -> None:
        turn = await _begin()
        await live_turn.publish(turn, "turn_prompt", {"content": "Anna asks"})
        store.on_listen = lambda: live_turn.end(turn)
        session = _session()
        # Nothing running when the chat is opened: the turn begins while it is open.
        # Heard twice - two tabs announcing - and followed once.
        begun = {"type": "turn_begun", "by": "anna"}
        room = self._room(events=[{"type": "presence"}, begun, begun])
        # Asked on opening, on the first announcement, and once the turn ends.
        with patch.object(live_turn, "live_token", AsyncMock(side_effect=[None, turn.token, None])):
            await self._enter(session, CONVERSATION, room)
        if session._follower is not None:
            await session._follower

        kinds = [kind for kind, _ in _sent_events(session)]
        assert kinds[:2] == ["turn_attached", "turn_prompt"]

    async def test_a_turn_begun_while_another_is_followed_is_followed_next(
        self, store: _Store
    ) -> None:
        """Two teammates asking at once: the second turn's announcement found the
        follower busy, and it used to be dropped until a reload."""
        first = await _begin()
        await live_turn.publish(first, "turn_prompt", {"content": "Anna asks"})
        second = await _begin()
        await live_turn.publish(second, "turn_prompt", {"content": "Kacper asks"})
        ending = [first, second]

        async def end_the_next() -> None:
            await live_turn.end(ending.pop(0))

        store.on_listen = end_the_next
        session = _session()

        await session._follow(CONVERSATION, first.token)

        prompts = [data["content"] for kind, data in _sent_events(session) if kind == "turn_prompt"]
        assert prompts == ["Anna asks", "Kacper asks"]
        assert [kind for kind, _ in _sent_events(session)].count(live_turn.END) == 2

    async def test_a_turn_this_socket_writes_is_not_followed_by_it(self, store: _Store) -> None:
        await _begin()
        session = _session()
        session._live = CONVERSATION
        await session._follow_if_running(CONVERSATION)
        assert session._follower is None

    async def test_a_teammates_turn_begun_during_this_sockets_own_is_followed_after_it(
        self, store: _Store
    ) -> None:
        session = _session()
        session._room = _CONVERSATION
        follow = AsyncMock()
        with (
            patch.object(session, "_follow_if_running", follow),
            _chat(AsyncMock(return_value=_finished_turn())),
        ):
            await session.process_message(_message())
        follow.assert_awaited_once_with(_CONVERSATION)

    async def test_moving_to_another_chat_or_none_leaves_the_room(self) -> None:
        session = _session()
        room = self._room()
        await self._enter(session, CONVERSATION, room)
        # The same chat again: still in its room, not joined twice.
        await self._enter(session, CONVERSATION, room)
        assert room["join"].await_count == 1

        await self._enter(session, None, room)
        room["leave"].assert_awaited_once_with(CONVERSATION, session.user.id, session._socket)
        assert session._room is None

    async def test_a_chat_that_cannot_be_read_leaves_the_room_it_was_in(self) -> None:
        session = _session()
        room = self._room()
        await self._enter(session, CONVERSATION, room)
        await self._enter(session, str(uuid4()), room, found=False)
        room["leave"].assert_awaited_once_with(CONVERSATION, session.user.id, session._socket)

    async def test_a_socket_that_closes_leaves(self) -> None:
        session = _session()
        room = self._room()
        await self._enter(session, CONVERSATION, room)
        with patch.multiple("app.services.agent_session.chat_room", **room):
            await session.shutdown()
        room["leave"].assert_awaited_once_with(CONVERSATION, session.user.id, session._socket)

    async def test_a_socket_already_closed_joins_no_room_and_follows_nothing(
        self, store: _Store
    ) -> None:
        """A turn running past its socket, or an attach mid-query when it went,
        must not count a closed tab as here until its entry expires."""
        await _begin()
        session = _session()
        room = self._room()
        with patch.multiple("app.services.agent_session.chat_room", **room):
            await session.shutdown()
        await self._enter(session, CONVERSATION, room)
        await session._follow_if_running(CONVERSATION)
        room["join"].assert_not_awaited()
        assert session._room is None and session._follower is None

    async def test_a_socket_closing_while_it_joins_takes_the_join_back(self) -> None:
        session = _session()
        room = self._room()

        async def closing(*_args: Any) -> None:
            session._closed = True

        room["join"] = AsyncMock(side_effect=closing)
        await self._enter(session, CONVERSATION, room)
        room["leave"].assert_awaited_once_with(CONVERSATION, session.user.id, session._socket)
        assert session._room_task is None

    async def test_a_turn_found_after_the_socket_closed_is_not_followed(
        self, store: _Store
    ) -> None:
        turn = await _begin()
        session = _session()
        session._room = CONVERSATION

        async def closing(_conversation: str) -> str:
            session._closed = True
            return turn.token

        with patch.object(live_turn, "live_token", AsyncMock(side_effect=closing)):
            await session._follow_if_running(CONVERSATION)
        assert session._follower is None

    async def test_a_turn_in_a_room_this_socket_left_is_not_followed(self, store: _Store) -> None:
        await _begin()
        session = _session()
        session._room = str(uuid4())
        await session._follow_if_running(CONVERSATION)
        assert session._follower is None

    async def test_unfollowing_stops_drawing_the_turn_and_stays_in_the_room(
        self, store: _Store
    ) -> None:
        """Stop on a teammate's turn is not this person's to send: their tab stops
        drawing it, and the room still counts them."""
        session = _session()
        session._room = CONVERSATION
        follower = asyncio.create_task(asyncio.Event().wait())
        session._follower = follower
        await session.handle_frame({"type": "unfollow"})
        await asyncio.gather(follower, return_exceptions=True)
        assert follower.cancelled()
        assert session._room == CONVERSATION

    async def test_a_follow_that_fails_ends_the_turn_for_the_tab(self, store: _Store) -> None:
        session = _session()
        with patch.object(session, "_follow_one", AsyncMock(side_effect=RuntimeError("redis"))):
            await session._follow(CONVERSATION, "token")
        assert _sent_events(session) == [(live_turn.END, {"conversation_id": CONVERSATION})]

    async def test_a_busy_room_asks_about_its_reader_once_a_while(self) -> None:
        """Each keystroke announced asked again: a credential, membership and
        conversation query per reader per announcement."""
        session = _session()
        typing = {"type": "typing", "by": str(uuid4())}
        room = self._room(events=[typing, typing, typing])
        reads = AsyncMock(return_value=True)
        with (
            patch.object(session, "_still_reads", reads),
            patch.multiple("app.services.agent_session.chat_room", **room),
            patch(
                "app.services.agent_session.conversation_repo.users_by_id",
                AsyncMock(return_value={}),
            ),
        ):
            await session._hear_room(CONVERSATION)
        assert reads.await_count == 1

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
        with patch.object(live_turn, "live_token", AsyncMock(return_value=None)):
            await self._enter(session, CONVERSATION, room, reads=False)
        room["leave"].assert_awaited_once_with(CONVERSATION, session.user.id, session._socket)
        assert session._room is None and session._follower is None

    async def test_a_followed_turn_asks_again_and_ends_for_somebody_removed(
        self, store: _Store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.agent_session.RECHECK_SECONDS", 0)
        turn = await _begin()
        await live_turn.publish(turn, "text_delta", {"content": "secret"})
        session = _session()
        with patch.object(session, "_still_reads", AsyncMock(return_value=False)):
            await session._follow(CONVERSATION, turn.token)
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
            await session._follow(CONVERSATION, turn.token)
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

    @pytest.mark.security
    async def test_a_revoked_session_does_not_and_its_socket_is_closed(self) -> None:
        """Membership and access outlive a revoked login; an idle socket sends no
        frame to re-check it, so the room's news does."""
        websocket = MagicMock(send_json=AsyncMock(), close=AsyncMock())
        session = AgentSession(websocket, _session().user, MagicMock(), auth_token="revoked")
        member = AsyncMock(return_value=MagicMock())
        with (
            self._db() as db_context,
            patch(
                "app.services.agent_session.authenticate_socket_token",
                AsyncMock(side_effect=AuthenticationError(message="Session ended")),
            ),
            patch("app.services.agent_session.member_repo.get", member),
        ):
            db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_context.return_value.__aexit__ = AsyncMock(return_value=False)
            assert await session._still_reads(CONVERSATION) is False

        websocket.close.assert_awaited_once()
        member.assert_not_awaited()
