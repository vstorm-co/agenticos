"""The Matrix adapter: reading `/sync`, and answering over the Client-Server API (#2081).

The homeserver is an `httpx.MockTransport` that records every call, so what is
asserted is the request the homeserver would receive: the room and thread it
goes to, whether it can notify anybody, and what an edit or a reaction is.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch
from urllib.parse import quote
from uuid import uuid4

import httpx
import pytest

from app.agents.capabilities.channel_tools import ChannelDirectoryUnsupported
from app.services.channels import matrix
from app.services.channels.base import (
    ChannelChoice,
    IncomingAttachment,
    IncomingMessage,
    IncomingPress,
    OutgoingAttachment,
    OutgoingMessage,
    PromptMessage,
)
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.matrix import MatrixAdapter, _Account
from app.services.channels.matrix_protocol import MESSAGE_LIMIT, room_key

pytestmark = pytest.mark.anyio

BOT = "bot-1"
BASE = "https://matrix.example.org"
OWN = "@agent:example.org"
ROOM = "!room:example.org"
DM = "!dm:example.org"
USER = "@ada:example.org"
API = "/_matrix/client/v3"


def _room_path(room: str, *parts: str, api: str = API) -> str:
    """A room's path as the adapter writes it, every segment percent-encoded."""
    return f"{api}/rooms/" + "/".join(quote(part, safe="") for part in (room, *parts))


def _relations(room: str, root: str) -> str:
    """Where a thread's replies are listed: `/relations` exists only under `v1`."""
    return _room_path(room, "relations", root, "m.thread", api="/_matrix/client/v1")


class _Homeserver:
    """A homeserver, recording each call and answering from `routes`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.routes: dict[tuple[str, str], list[httpx.Response]] = {}
        self._next = 0

    def answer(self, method: str, path: str, *responses: httpx.Response) -> None:
        self.routes[(method, path)] = list(responses)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode().split("?")[0]
        body: Any = None
        if request.content and request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            body = json.loads(request.content)
        elif request.content:
            body = request.content
        self.calls.append((request.method, path, body))
        if "/_matrix/client/v3/rooms/" in path and "/relations/" in path:
            return httpx.Response(404, json={"errcode": "M_UNRECOGNIZED"})
        queued = self.routes.get((request.method, path))
        if queued:
            return queued.pop(0) if len(queued) > 1 else queued[0]
        for (method, prefix), responses in self.routes.items():
            if method == request.method and prefix.endswith("*") and path.startswith(prefix[:-1]):
                return responses[0]
        if request.method == "GET" and path.endswith("/state/m.room.encryption/"):
            return httpx.Response(404, json={"errcode": "M_NOT_FOUND"})
        self._next += 1
        return httpx.Response(200, json={"event_id": f"$sent{self._next}"})

    def sent(self, event_type: str = "m.room.message") -> list[tuple[str, Any]]:
        return [
            (path, body)
            for method, path, body in self.calls
            if method == "PUT" and f"/send/{event_type}/" in path
        ]


@pytest.fixture
def server() -> _Homeserver:
    return _Homeserver()


@pytest.fixture
def adapter(server: _Homeserver) -> MatrixAdapter:
    built = MatrixAdapter(transport=httpx.MockTransport(server.handle))
    built.prepare_connection(BOT, api_base_url=f"{BASE}/", app_token=None)
    built._accounts[BOT] = _Account(user_id=OWN, display_name="Agent")
    return built


def _event(body: str = "hello", **content: Any) -> dict[str, Any]:
    return {
        "type": "m.room.message",
        "event_id": "$question",
        "sender": USER,
        "origin_server_ts": 1_700_000_000_000,
        "content": {"msgtype": "m.text", "body": body, **content},
    }


def _out(text: str, chat: str | None = None) -> OutgoingMessage:
    return OutgoingMessage(
        platform_chat_id=chat or f"{room_key(ROOM)}:$question", text=text, api_base_url=BASE
    )


class TestReading:
    def test_a_mention_in_a_room_is_a_question_keyed_on_its_own_thread(
        self, adapter: MatrixAdapter
    ):
        incoming = adapter.parse_incoming(
            {
                "room_id": ROOM,
                "event": _event(
                    "Agent: what is the refund window?", **{"m.mentions": {"user_ids": [OWN]}}
                ),
                "direct": False,
            },
            BOT,
        )
        assert incoming is not None
        assert incoming.platform_chat_id == f"{room_key(ROOM, server_url=BASE)}:$question"
        assert (incoming.chat_type, incoming.addressed) == ("group", True)
        assert incoming.text == "what is the refund window?"
        assert incoming.platform_user_id == USER

    def test_a_reply_in_a_thread_continues_the_threads_conversation(self, adapter: MatrixAdapter):
        event = _event(
            "and next?", **{"m.relates_to": {"rel_type": "m.thread", "event_id": "$root"}}
        )
        incoming = adapter.parse_incoming(
            {"room_id": ROOM, "event": event, "direct": False, "bot_thread": True}, BOT
        )
        assert incoming is not None
        assert incoming.platform_chat_id == f"{room_key(ROOM, server_url=BASE)}:$root"
        assert incoming.addressed is True

    def test_a_room_message_that_names_nobody_is_not_addressed(self, adapter: MatrixAdapter):
        incoming = adapter.parse_incoming(
            {"room_id": ROOM, "event": _event("lunch?", **{"m.mentions": {}}), "direct": False}, BOT
        )
        assert incoming is not None and incoming.addressed is False

    def test_everything_in_a_direct_chat_is_to_the_bot(self, adapter: MatrixAdapter):
        incoming = adapter.parse_incoming({"room_id": DM, "event": _event(), "direct": True}, BOT)
        assert incoming is not None
        assert (incoming.chat_type, incoming.addressed) == ("private", True)

    def test_the_bots_own_messages_are_never_read(self, adapter: MatrixAdapter):
        event = {**_event(), "sender": OWN}
        assert adapter.parse_incoming({"room_id": DM, "event": event, "direct": True}, BOT) is None

    def test_a_room_mention_is_a_broadcast(self, adapter: MatrixAdapter):
        incoming = adapter.parse_incoming(
            {
                "room_id": ROOM,
                "event": _event("@room deploy at five", **{"m.mentions": {"room": True}}),
            },
            BOT,
        )
        assert incoming is not None
        assert (incoming.broadcast_mention, incoming.addressed) == (True, False)


class TestSync:
    async def test_failed_admission_does_not_advance_the_durable_sync_cursor(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET",
            _room_path(DM, "joined_members"),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}}}),
        )
        batch = {"next_batch": "s9", "rooms": {"join": {DM: {"timeline": {"events": [_event()]}}}}}
        redis = AsyncMock()
        redis.get.return_value = "s8"
        with (
            patch.object(matrix, "_redis", redis),
            patch.object(adapter, "_account", AsyncMock(return_value=adapter._accounts[BOT])),
            patch.object(adapter, "_sync", AsyncMock(return_value=batch)),
            patch.object(matrix.connection_state, "record_up", AsyncMock()),
            patch(
                "app.services.channels.ingress.admit_message",
                AsyncMock(side_effect=RuntimeError("unavailable")),
            ),
            pytest.raises(ExceptionGroup),
        ):
            await adapter._run_stream(BOT, "tok")
        redis.set.assert_not_awaited()

    @pytest.mark.security
    async def test_a_room_encrypted_after_joining_admits_no_plaintext(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET",
            _room_path(DM, "state", "m.room.encryption", ""),
            httpx.Response(200, json={"algorithm": "m.megolm.v1.aes-sha2"}),
        )
        admitted = AsyncMock()
        with patch("app.services.channels.ingress.admit_message", admitted):
            await adapter._on_sync(
                BOT,
                "tok",
                BASE,
                adapter._accounts[BOT],
                {"rooms": {"join": {DM: {"timeline": {"events": [_event()]}}}}},
                backlog=False,
            )
        admitted.assert_not_awaited()

    async def test_encryption_enabled_during_a_run_stops_its_reply(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        from app.agents.capabilities.channel_tools import ChannelDirectoryUnsupported

        handle = await adapter.begin_reply("tok", _out("working"))
        assert handle is not None
        server.answer(
            "GET",
            _room_path(ROOM, "state", "m.room.encryption", ""),
            httpx.Response(200, json={"algorithm": "m.megolm.v1.aes-sha2"}),
        )
        before = len(server.sent())
        with pytest.raises(ChannelDirectoryUnsupported, match="encrypted"):
            await adapter.update_reply("tok", _out("confidential result"), handle)
        assert len(server.sent()) == before

    @pytest.mark.security
    async def test_an_unreadable_encryption_state_never_posts_plaintext(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET", _room_path(ROOM, "state", "m.room.encryption", ""), httpx.Response(503)
        )
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.send_message("tok", _out("confidential result"))
        assert server.sent() == []

    async def test_a_malformed_file_does_not_stop_the_next_message_in_a_batch(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET",
            _room_path(DM, "joined_members"),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}}}),
        )
        bad = _event(
            "file", msgtype="m.file", url="mxc://example.org/file", info={"size": "invalid"}
        )
        admitted = AsyncMock()
        with patch("app.services.channels.ingress.admit_message", admitted):
            await adapter._on_sync(
                BOT,
                "tok",
                BASE,
                adapter._accounts[BOT],
                {"rooms": {"join": {DM: {"timeline": {"events": [bad, _event("next")]}}}}},
                backlog=False,
            )
        assert admitted.await_count == 1
        assert admitted.await_args.args[0].text == "next"

    async def test_the_first_sync_skips_the_backlog_and_a_later_one_admits_messages(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        batch = {
            "next_batch": "s2",
            "rooms": {"join": {DM: {"timeline": {"events": [_event()]}}}},
        }
        server.answer(
            "GET",
            _room_path(DM, "joined_members"),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}}}),
        )
        admitted: list[IncomingMessage] = []

        async def admit(incoming: IncomingMessage) -> None:
            admitted.append(incoming)

        with patch("app.services.channels.ingress.admit_message", admit):
            await adapter._on_sync(BOT, "tok", BASE, adapter._accounts[BOT], batch, backlog=True)
            assert admitted == []
            await adapter._on_sync(BOT, "tok", BASE, adapter._accounts[BOT], batch, backlog=False)
        assert [item.chat_type for item in admitted] == ["private"]

    async def test_a_room_whose_members_cannot_be_counted_is_a_room(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        """A group mistaken for a private chat would read the speaker's private memory (#1470)."""
        server.answer("GET", _room_path(DM, "joined_members"), httpx.Response(500, text=""))
        assert await adapter._is_direct(BOT, "tok", BASE, DM) is False

    async def test_a_session_resumes_from_the_stored_position(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        server.answer("GET", f"{API}/account/whoami", httpx.Response(200, json={"user_id": OWN}))
        server.answer(
            "GET",
            f"{API}/sync",
            httpx.Response(200, json={"next_batch": "s9"}),
            httpx.Response(503),
        )
        redis = AsyncMock()
        redis.get.return_value = "s8"
        with (
            patch.object(matrix, "_redis", redis),
            patch.object(matrix.connection_state, "record_up", AsyncMock()),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await adapter._run_stream(BOT, "tok")
        assert redis.set.await_args.args[1] == "s9"
        assert redis.get.await_args.args[0] == redis.set.await_args.args[0]

    async def test_a_rejected_token_stops_the_bot_with_a_reason(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        server.answer(
            "GET",
            f"{API}/account/whoami",
            httpx.Response(401, json={"errcode": "M_UNKNOWN_TOKEN"}),
        )
        with pytest.raises(ChannelNotConfigured, match="rejected the Matrix access token"):
            await adapter._run_stream(BOT, "tok")

    async def test_a_bot_without_a_homeserver_is_not_started(self, adapter: MatrixAdapter):
        with pytest.raises(ChannelNotConfigured, match="homeserver URL"):
            await adapter._run_stream("another-bot", "tok")

    @pytest.mark.parametrize(("admitted", "action"), [(True, "join"), (False, "leave")])
    async def test_an_invitation_is_taken_only_from_somebody_the_policy_admits(
        self, adapter: MatrixAdapter, server: _Homeserver, admitted: bool, action: str
    ):
        invite = {
            "invite_state": {
                "events": [
                    {
                        "type": "m.room.member",
                        "state_key": OWN,
                        "sender": USER,
                        "content": {"membership": "invite", "is_direct": True},
                    }
                ]
            }
        }
        check = AsyncMock(return_value=admitted)
        with patch("app.services.channels.ingress.invite_admitted", check):
            await adapter._on_sync(
                BOT,
                "tok",
                BASE,
                adapter._accounts[BOT],
                {"next_batch": "s1", "rooms": {"invite": {ROOM: invite}}},
                backlog=True,
            )
        assert check.await_args.args == (BOT, USER, room_key(ROOM))
        assert check.await_args.kwargs == {"direct": True, "server_url": BASE}
        assert ("POST", _room_path(ROOM, action), {}) in server.calls

    async def test_an_encrypted_room_is_declined_with_a_reason_before_policy_is_asked(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        """It would join and then read nothing there, which looks like a broken bot."""
        invite = {
            "invite_state": {
                "events": [
                    {"type": "m.room.encryption", "state_key": "", "content": {}},
                    {
                        "type": "m.room.member",
                        "state_key": OWN,
                        "sender": USER,
                        "content": {"membership": "invite"},
                    },
                ]
            }
        }
        check = AsyncMock(return_value=True)
        with patch("app.services.channels.ingress.invite_admitted", check):
            await adapter._on_sync(
                BOT,
                "tok",
                BASE,
                adapter._accounts[BOT],
                {"next_batch": "s1", "rooms": {"invite": {ROOM: invite}}},
                backlog=True,
            )
        check.assert_not_awaited()
        [(_, path, body)] = [call for call in server.calls if call[0] == "POST"]
        assert path == _room_path(ROOM, "leave")
        assert "encrypted" in body["reason"]

    async def test_a_gap_in_a_busy_room_is_filled_back_to_the_last_message_read(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        """A limited sync shows only its newest events; the ones before them are fetched.

        Only those newer than the last message read: an older one was answered
        before the gap.
        """
        server.answer(
            "GET",
            _room_path(ROOM, "messages"),
            httpx.Response(
                200,
                json={
                    "chunk": [
                        {**_event("in the gap"), "event_id": "$gap", "origin_server_ts": 2_000},
                    ]
                },
            ),
        )
        server.answer(
            "GET",
            _room_path(ROOM, "joined_members"),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}, "@b:x": {}}}),
        )
        batch = {
            "next_batch": "s3",
            "rooms": {
                "join": {
                    ROOM: {
                        "timeline": {
                            "limited": True,
                            "prev_batch": "p1",
                            "events": [
                                {**_event("newest"), "event_id": "$new", "origin_server_ts": 3_000}
                            ],
                        }
                    }
                }
            },
        }
        admitted: list[IncomingMessage] = []

        async def admit(incoming: IncomingMessage) -> None:
            admitted.append(incoming)

        with patch("app.services.channels.ingress.admit_message", admit):
            await adapter._on_sync(
                BOT, "tok", BASE, adapter._accounts[BOT], batch, backlog=False, since="s0"
            )
        assert [item.message_id for item in admitted] == ["$gap", "$new"]

    async def test_a_gap_after_a_restart_is_logged_not_guessed_at(
        self, adapter: MatrixAdapter, server: _Homeserver, caplog: pytest.LogCaptureFixture
    ):
        timeline = {"limited": True, "prev_batch": "p1", "events": []}
        assert [
            event async for event in adapter._gap(BOT, "tok", BASE, ROOM, timeline, since=None)
        ] == []
        assert not [call for call in server.calls if "/messages" in call[1]]
        assert "matrix_timeline_gap_skipped" in caplog.text

    async def test_the_sender_is_named_and_a_membership_change_in_state_resets_the_room(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        adapter._direct.put(f"{BOT}:{DM}", True)
        server.answer(
            "GET",
            _room_path(DM, "joined_members"),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}, "@b:x": {}}}),
        )
        member = {
            "type": "m.room.member",
            "state_key": USER,
            "content": {"membership": "join", "displayname": "Ada Lovelace"},
        }
        batch = {
            "next_batch": "s2",
            "rooms": {
                "join": {
                    DM: {
                        "state": {"events": [member]},
                        "timeline": {
                            "events": [_event("hi", **{"m.mentions": {"user_ids": [OWN]}})]
                        },
                    }
                }
            },
        }
        admitted: list[IncomingMessage] = []

        async def admit(incoming: IncomingMessage) -> None:
            admitted.append(incoming)

        with patch("app.services.channels.ingress.admit_message", admit):
            await adapter._on_sync(BOT, "tok", BASE, adapter._accounts[BOT], batch, backlog=False)
        [incoming] = admitted
        assert incoming.platform_display_name == "Ada Lovelace"
        assert incoming.chat_type == "group", "a third member arrived: no longer a direct chat"

    async def test_a_thread_rooted_at_a_question_to_the_bot_is_the_bots(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        server.answer(
            "GET",
            _room_path(ROOM, "event", "$root"),
            httpx.Response(
                200,
                json={**_event("hi", **{"m.mentions": {"user_ids": [OWN]}}), "event_id": "$root"},
            ),
        )
        event = _event("more", **{"m.relates_to": {"rel_type": "m.thread", "event_id": "$root"}})
        account = adapter._accounts[BOT]
        assert await adapter._in_bot_thread(BOT, "tok", BASE, account, ROOM, event) is True
        assert await adapter._in_bot_thread(BOT, "tok", BASE, account, ROOM, event) is True
        lookups = [call for call in server.calls if call[1].endswith("/event/%24root")]
        assert len(lookups) == 1


class TestAnswering:
    async def test_a_reply_goes_into_the_questions_thread(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        await adapter.send_message("tok", _out("the answer"))
        [(path, body)] = server.sent()
        assert path.startswith(_room_path(ROOM, "send", "m.room.message"))
        assert body["m.relates_to"]["event_id"] == "$question"
        assert body["m.mentions"] == {}

    async def test_a_file_is_uploaded_and_posted_after_the_text(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        server.answer(
            "POST",
            "/_matrix/media/v3/upload",
            httpx.Response(200, json={"content_uri": "mxc://h/f"}),
        )
        message = _out("here it is")
        message.attachments = [OutgoingAttachment("a.csv", b"1,2", "text/csv")]
        await adapter.send_message("tok", message)
        bodies = [body for _, body in server.sent()]
        assert bodies[0]["body"] == "here it is"
        assert (bodies[1]["msgtype"], bodies[1]["url"]) == ("m.file", "mxc://h/f")
        assert bodies[1]["m.relates_to"]["event_id"] == "$question"

    async def test_an_answer_is_edited_into_place_and_spills_past_the_limit(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        handle = await adapter.begin_reply("tok", _out("Working…"))
        assert handle is not None
        await adapter.update_reply("tok", _out("Working…"), handle)
        assert len(server.sent()) == 1, "an unchanged part is not edited"
        await adapter.update_reply("tok", _out("x " * MESSAGE_LIMIT), handle)
        edit, spill = (body for _, body in server.sent()[1:])
        assert edit["m.relates_to"] == {"rel_type": "m.replace", "event_id": handle}
        assert spill["m.relates_to"]["rel_type"] == "m.thread"
        await adapter.update_reply("tok", _out("short"), handle)
        assert any(method == "PUT" and "/redact/" in path for method, path, _ in server.calls)

    async def test_failed_redaction_remains_pending_for_the_next_update(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        handle = await adapter.begin_reply("tok", _out("working"))
        assert handle is not None
        await adapter.update_reply("tok", _out("x" * (MESSAGE_LIMIT + 20)), handle)
        reply = adapter._replies.get(matrix._reply_key(BASE, "tok", handle))
        assert reply is not None
        stale = reply.ids[-1]
        redact_path = _room_path(ROOM, "redact", stale) + "/"
        original = adapter._call
        failed = False

        async def call(method: str, url: str, token: str, **kwargs: Any) -> httpx.Response:
            nonlocal failed
            if "/redact/" in url and not failed:
                failed = True
                return httpx.Response(503, request=httpx.Request(method, url))
            return await original(method, url, token, **kwargs)

        with patch.object(adapter, "_call", call):
            with pytest.raises(httpx.HTTPStatusError):
                await adapter.update_reply("tok", _out("safe"), handle)
            assert stale in reply.ids
            await adapter.update_reply("tok", _out("safe"), handle)
        assert stale not in reply.ids
        assert any(
            method == "PUT" and path.startswith(redact_path) for method, path, _ in server.calls
        )

    async def test_an_edit_from_another_worker_finds_its_room_from_the_chat(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        await adapter.update_reply("tok", _out("done"), "$elsewhere")
        [(path, body)] = server.sent()
        assert path.startswith(_room_path(ROOM, "send"))
        assert body["m.relates_to"]["event_id"] == "$elsewhere"

    async def test_a_rate_limit_is_waited_out(self, adapter: MatrixAdapter, server: _Homeserver):
        server.answer(
            "PUT",
            _room_path(ROOM, "send", "m.room.message") + "/*",
            httpx.Response(429, json={"errcode": "M_LIMIT_EXCEEDED", "retry_after_ms": 0}),
        )
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.send_message("tok", _out("hi"))
        assert len(server.sent()) == 4

    async def test_a_reply_without_a_homeserver_is_refused(self, adapter: MatrixAdapter):
        with pytest.raises(ValueError, match="homeserver URL"):
            await adapter.send_message(
                "tok", OutgoingMessage(platform_chat_id=room_key(ROOM), text="hi")
            )


class TestPrompts:
    async def test_an_approval_is_numbered_in_its_thread(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        prompt = PromptMessage(
            platform_chat_id=f"{room_key(ROOM)}:$question",
            text="Send the e-mail?",
            choices=[ChannelChoice("Approve", "aos:p:0"), ChannelChoice("Deny", "aos:p:1")],
            bot_id=BOT,
            api_base_url=BASE,
        )
        with (
            patch.object(matrix.sms_prompts, "reserve", AsyncMock(return_value=3)) as reserve,
            patch.object(matrix.sms_prompts, "remember", AsyncMock()) as remember,
        ):
            await adapter.send_prompt("tok", prompt)
        [(_, body)] = server.sent()
        assert "3. Approve\n4. Deny" in body["body"]
        assert body["m.relates_to"]["event_id"] == "$question"
        assert reserve.await_args.kwargs == {"platform": "matrix"}
        assert remember.await_args.args[2] == ["aos:p:0", "aos:p:1"]

    async def test_a_decision_is_said_and_its_numbers_stop_answering(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        press = IncomingPress(
            platform="matrix",
            bot_id=BOT,
            platform_user_id=USER,
            platform_chat_id=f"{room_key(ROOM)}:$question",
            value="aos:p:0",
        )
        with (
            patch.object(matrix.sms_prompts, "settle", AsyncMock()) as settle,
            patch.object(MatrixAdapter, "_homeserver", AsyncMock(return_value=BASE)),
        ):
            await adapter.settle_prompt("tok", press, "Approved")
        assert settle.await_args.kwargs == {"platform": "matrix"}
        assert server.sent()[0][1]["body"] == "Approved"


class TestReactions:
    @pytest.mark.parametrize("explicit_server", [False, True])
    async def test_a_question_is_acknowledged_with_the_emoji(
        self, adapter: MatrixAdapter, server: _Homeserver, explicit_server: bool
    ):
        incoming = IncomingMessage(
            platform="matrix",
            bot_id=BOT,
            platform_user_id=USER,
            platform_chat_id=f"{room_key(ROOM)}:$question",
            chat_type="group",
            text="hi",
            message_id="$question",
        )
        with patch.object(MatrixAdapter, "_homeserver", AsyncMock(return_value=BASE)) as resolve:
            await adapter.acknowledge_message(
                "tok", incoming, "eyes", api_base_url=BASE if explicit_server else None
            )
        assert resolve.await_count == (0 if explicit_server else 1)
        [(_, body)] = server.sent("m.reaction")
        assert body == {
            "m.relates_to": {"rel_type": "m.annotation", "event_id": "$question", "key": "👀"}
        }

    async def test_the_router_s_homeserver_is_used_without_looking_the_bot_up(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        incoming = IncomingMessage(
            platform="matrix",
            bot_id=BOT,
            platform_user_id=USER,
            platform_chat_id=f"{room_key(ROOM)}:$question",
            chat_type="group",
            text="hi",
            message_id="$question",
        )
        lookup = AsyncMock(return_value="https://elsewhere.example")
        with patch.object(MatrixAdapter, "_homeserver", lookup):
            await adapter.acknowledge_message("tok", incoming, "eyes", api_base_url=f"{BASE}/")
        lookup.assert_not_awaited()
        assert len(server.sent("m.reaction")) == 1

    async def test_a_reaction_to_a_message_in_another_room_is_refused(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        from app.agents.capabilities.channel_tools import ChannelDirectoryUnsupported

        server.answer(
            "GET",
            _room_path(ROOM, "event", "$other"),
            httpx.Response(200, json={"room_id": "!elsewhere:example.org"}),
        )
        with pytest.raises(ChannelDirectoryUnsupported):
            await adapter.react_to_message(
                "tok", room_key(ROOM), "$other", "thumbsup", api_base_url=BASE
            )
        assert server.sent("m.reaction") == []


class TestTypingAndHomeserver:
    async def test_typing_reuses_the_reply_just_opened_and_reads_no_token(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        server.answer("GET", f"{API}/account/whoami", httpx.Response(200, json={"user_id": OWN}))
        await adapter.typing(BOT, _out("Working…"))
        assert not [call for call in server.calls if "/typing/" in call[1]], "no reply opened yet"
        await adapter.begin_reply("tok", _out("Working…"))
        await adapter.typing(BOT, _out("Working…"))
        [(method, path, body)] = [call for call in server.calls if "/typing/" in call[1]]
        assert (method, body) == ("PUT", {"typing": True, "timeout": 30_000})
        assert path.endswith(quote(OWN, safe=""))

    async def test_the_homeserver_is_read_off_the_row_once_and_not_the_token(self):
        from app.db.models.channel_bot import ChannelBot

        row = ChannelBot(platform="matrix", api_base_url=f"{BASE}/", token_encrypted="sealed")
        lookup = AsyncMock(return_value=row)

        @asynccontextmanager
        async def session():
            yield object()

        fresh = MatrixAdapter()
        with (
            patch("app.db.session.get_db_context", session),
            patch("app.repositories.channel_bot_repo.get_for_inbound", lookup),
        ):
            assert await fresh._homeserver(str(uuid4())) == BASE
            bot = lookup.await_args.args[1]
            assert await fresh._homeserver(str(bot)) == BASE
        assert lookup.await_count == 1

    async def test_a_bot_whose_row_names_no_homeserver_is_refused(self):
        @asynccontextmanager
        async def session():
            yield object()

        with (
            patch("app.db.session.get_db_context", session),
            patch(
                "app.repositories.channel_bot_repo.get_for_inbound", AsyncMock(return_value=None)
            ),
            pytest.raises(ChannelNotConfigured, match="no homeserver URL"),
        ):
            await MatrixAdapter()._homeserver(str(uuid4()))


class TestHistoryAndFiles:
    async def test_a_threads_history_is_its_root_and_replies_as_edited(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        server.answer(
            "GET",
            _relations(ROOM, "$root"),
            httpx.Response(
                200,
                json={
                    "chunk": [
                        {
                            **_event("…"),
                            "event_id": "$answer",
                            "sender": OWN,
                            "unsigned": {
                                "m.relations": {
                                    "m.replace": {
                                        "content": {
                                            "m.new_content": {
                                                "msgtype": "m.text",
                                                "body": "30 days",
                                            }
                                        }
                                    }
                                }
                            },
                        }
                    ]
                },
            ),
        )
        server.answer(
            "GET",
            _room_path(ROOM, "event", "$root"),
            httpx.Response(200, json={**_event("refund window?"), "event_id": "$root"}),
        )
        posts = await adapter.channel_history(
            "tok", room_key(ROOM), api_base_url=BASE, limit=10, thread_id="$root"
        )
        assert [(post.post_id, post.text) for post in posts] == [
            ("$root", "refund window?"),
            ("$answer", "30 days"),
        ]

    async def test_a_file_past_the_upload_limit_is_not_read_to_the_end(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        handle = f"{BASE}/_matrix/client/v1/media/download/example.org/big"
        server.answer(
            "GET",
            "/_matrix/client/v1/media/download/example.org/big",
            httpx.Response(200, content=b"x" * 64),
        )
        attachment = IncomingAttachment("big.bin", "application/octet-stream", 0, handle)
        with (
            patch.object(matrix.settings, "CHAT_MAX_UPLOAD_SIZE_MB", 0),
            pytest.raises(ValueError, match="upload limit"),
        ):
            await adapter.download_attachment("tok", attachment)

    async def test_a_file_is_fetched_with_the_bots_token(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        handle = f"{BASE}/_matrix/client/v1/media/download/example.org/small"
        server.answer(
            "GET",
            "/_matrix/client/v1/media/download/example.org/small",
            httpx.Response(200, content=b"ok"),
        )
        assert (
            await adapter.download_attachment(
                "tok", IncomingAttachment("s.txt", "text/plain", 2, handle)
            )
            == b"ok"
        )

    async def test_the_bots_own_uploads_are_left_out_of_a_threads_files(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        server.answer("GET", f"{API}/account/whoami", httpx.Response(200, json={"user_id": OWN}))
        file = {"msgtype": "m.file", "url": "mxc://example.org/f", "info": {"size": 1}}
        server.answer(
            "GET",
            _relations(ROOM, "$root"),
            httpx.Response(
                200,
                json={
                    "chunk": [
                        {**_event("chart.png", **file), "event_id": "$mine", "sender": OWN},
                        {**_event("data.csv", **file), "event_id": "$theirs"},
                    ]
                },
            ),
        )
        server.answer("GET", _room_path(ROOM, "event", "$root"), httpx.Response(404))
        found = await adapter.thread_attachments(
            "tok", room_key(ROOM), thread_id="$root", api_base_url=BASE, limit=10
        )
        assert [item.filename for item in found] == ["data.csv"]

    async def test_membership_is_the_rooms_joined_members(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        server.answer(
            "GET",
            _room_path(ROOM, "joined_members"),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {"display_name": "Ada"}}}),
        )
        assert await adapter.is_channel_member("tok", room_key(ROOM), USER, api_base_url=BASE)
        assert not await adapter.is_channel_member(
            "tok", room_key(ROOM), "@eve:example.org", api_base_url=BASE
        )


class TestFailureBoundaries:
    async def test_redis_can_be_withdrawn_and_a_stream_without_it_has_no_cursor(self) -> None:
        matrix.configure(None)
        assert await MatrixAdapter._load_since(BOT, OWN, BASE) is None
        await MatrixAdapter._store_since(BOT, OWN, "s1", BASE)

    async def test_stream_lifecycle_starts_once_and_cancels_before_shutdown(
        self, adapter: MatrixAdapter
    ) -> None:
        entered = asyncio.Event()

        async def session(bot_id: str, token: str) -> None:
            assert (bot_id, token) == (BOT, "tok")
            entered.set()
            await asyncio.Event().wait()

        with patch.object(adapter, "_run_stream", session):
            await adapter.start_polling(BOT, "tok")
            await entered.wait()
            task = adapter._sync_tasks[BOT]
            await adapter.start_polling(BOT, "tok")
            assert adapter._sync_tasks[BOT] is task
            await adapter.stop_polling(BOT)
            assert task.cancelled()
            assert BOT not in adapter._accounts
            await adapter.stop_polling(BOT)
        await adapter.aclose()

    async def test_completed_stream_can_be_replaced(self, adapter: MatrixAdapter) -> None:
        task = asyncio.create_task(asyncio.sleep(0))
        await task
        adapter._sync_tasks[BOT] = task
        with patch.object(adapter, "_supervise", AsyncMock()):
            await adapter.start_polling(BOT, "tok")
            replacement = adapter._sync_tasks[BOT]
            await replacement
            assert replacement is not task
            await adapter.stop_polling(BOT)

    async def test_unsupported_webhooks_are_always_refused(self, adapter: MatrixAdapter) -> None:
        assert not await adapter.register_webhook("tok", "https://example.org", "secret")
        assert not await adapter.delete_webhook("tok")
        assert not adapter.verify_webhook_signature({}, "secret", "body")

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"room_id": ROOM, "event": {}},
            {"room_id": ROOM, "event": _event("", **{"m.mentions": {}})},
            {"room_id": ROOM, "event": {**_event(), "sender": OWN}},
        ],
    )
    def test_incomplete_empty_and_own_events_do_not_become_questions(
        self, adapter: MatrixAdapter, payload: dict[str, Any]
    ) -> None:
        assert adapter.parse_incoming(payload, BOT) is None
        assert adapter.parse_incoming(payload, "unknown-bot") is None

    async def test_directory_refuses_missing_server_or_non_room(
        self, adapter: MatrixAdapter
    ) -> None:
        with pytest.raises(ChannelDirectoryUnsupported, match="homeserver"):
            await adapter.channel_details("tok", room_key(ROOM), api_base_url=None)
        with pytest.raises(ChannelDirectoryUnsupported, match="room"):
            await adapter.channel_details("tok", "general", api_base_url=BASE)
        assert await adapter._homeserver(BOT) == BASE

    @pytest.mark.parametrize("status", [403, 503])
    async def test_unavailable_membership_is_not_invented(
        self, adapter: MatrixAdapter, server: _Homeserver, status: int
    ) -> None:
        server.answer("GET", f"{API}/account/whoami", httpx.Response(200, json={"user_id": OWN}))
        server.answer("GET", _room_path(ROOM, "joined_members"), httpx.Response(status))
        error = ChannelDirectoryUnsupported if status == 403 else httpx.HTTPStatusError
        with pytest.raises(error):
            await adapter.channel_members("tok", room_key(ROOM), api_base_url=BASE, limit=10)

    async def test_room_details_and_bounded_members_use_the_homeserver_state(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer("GET", f"{API}/account/whoami", httpx.Response(200, json={"user_id": OWN}))
        server.answer(
            "GET",
            _room_path(ROOM, "joined_members"),
            httpx.Response(
                200, json={"joined": {OWN: {}, USER: {"display_name": "Ada"}, "@bob:x": None}}
            ),
        )
        for kind, content in [
            ("m.room.name", {"name": "Support"}),
            ("m.room.topic", {"topic": "Refunds"}),
            ("m.room.join_rules", {"join_rule": "public"}),
        ]:
            server.answer(
                "GET", _room_path(ROOM, "state", kind, ""), httpx.Response(200, json=content)
            )
        details = await adapter.channel_details("tok", room_key(ROOM), api_base_url=BASE)
        assert (details.name, details.topic, details.is_private, details.member_count) == (
            "Support",
            "Refunds",
            False,
            3,
        )
        members = await adapter.channel_members("tok", room_key(ROOM), api_base_url=BASE, limit=2)
        assert [(m.user_id, m.is_bot, m.display_name) for m in members] == [
            (OWN, True, None),
            (USER, False, "Ada"),
        ]
        members = await adapter.channel_members("tok", room_key(ROOM), api_base_url=BASE, limit=3)
        assert members[-1].display_name is None

    async def test_absent_state_has_safe_room_defaults(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        for kind in ["m.room.name", "m.room.topic", "m.room.join_rules"]:
            server.answer("GET", _room_path(ROOM, "state", kind, ""), httpx.Response(404))
        details = await adapter.channel_details("tok", room_key(ROOM), api_base_url=BASE)
        assert (details.name, details.topic, details.is_private, details.member_count) == (
            ROOM,
            None,
            True,
            0,
        )
        server.answer(
            "GET", _room_path(ROOM, "state", "m.room.name", ""), httpx.Response(200, json=[])
        )
        assert await adapter._state(BASE, "tok", ROOM, "m.room.name") == {}
        server.answer("GET", _room_path(ROOM, "state", "m.room.name", ""), httpx.Response(403))
        with pytest.raises(ChannelDirectoryUnsupported):
            await adapter.channel_details("tok", room_key(ROOM), api_base_url=BASE)

    async def test_reactions_validate_names_and_room_before_posting(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        incoming = IncomingMessage(
            platform="matrix",
            bot_id=BOT,
            platform_user_id=USER,
            platform_chat_id=room_key(ROOM),
            chat_type="group",
            text="hi",
        )
        await adapter.acknowledge_message("tok", incoming, "unknown")
        incoming.message_id = "$question"
        with pytest.raises(ValueError, match="reaction"):
            await adapter.acknowledge_message("tok", incoming, "unknown")
        with pytest.raises(ChannelDirectoryUnsupported, match="emoji"):
            await adapter.react_to_message(
                "tok", room_key(ROOM), "$question", "unknown", api_base_url=BASE
            )
        server.answer(
            "GET",
            _room_path(ROOM, "event", "$question"),
            httpx.Response(200, json={"room_id": ROOM}),
        )
        await adapter.react_to_message(
            "tok", room_key(ROOM), "$question", "eyes", api_base_url=BASE
        )
        assert server.sent("m.reaction")[-1][1]["m.relates_to"]["event_id"] == "$question"

    async def test_typing_failure_is_visible_and_does_not_lose_the_reply(
        self, adapter: MatrixAdapter, server: _Homeserver, caplog: pytest.LogCaptureFixture
    ) -> None:
        await adapter.begin_reply("tok", _out("working"))
        server.answer("GET", f"{API}/account/whoami", httpx.Response(503))
        await adapter.typing(BOT, _out("working"))
        assert "matrix_typing_failed" in caplog.text

    @pytest.mark.parametrize("handle,size", [("", 0), (f"{BASE}/file", 100)])
    async def test_missing_or_claimed_oversized_files_are_not_downloaded(
        self, adapter: MatrixAdapter, server: _Homeserver, handle: str, size: int
    ) -> None:
        with patch.object(matrix.settings, "CHAT_MAX_UPLOAD_SIZE_MB", 0), pytest.raises(ValueError):
            await adapter.download_attachment(
                "tok", IncomingAttachment("a", "text/plain", size, handle)
            )
        assert server.calls == []

    @pytest.mark.parametrize("status", [403, 503])
    async def test_thread_history_refuses_unreadable_rooms(
        self, adapter: MatrixAdapter, server: _Homeserver, status: int
    ) -> None:
        server.answer("GET", _relations(ROOM, "$root"), httpx.Response(status))
        error = ChannelDirectoryUnsupported if status == 403 else httpx.HTTPStatusError
        with pytest.raises(error):
            await adapter.channel_history(
                "tok", room_key(ROOM), api_base_url=BASE, limit=5, thread_id="$root"
            )

    @pytest.mark.parametrize("status", [404, 503])
    async def test_thread_root_missing_is_distinct_from_server_failure(
        self, adapter: MatrixAdapter, server: _Homeserver, status: int
    ) -> None:
        server.answer("GET", _relations(ROOM, "$root"), httpx.Response(200, json={"chunk": []}))
        server.answer("GET", _room_path(ROOM, "event", "$root"), httpx.Response(status))
        if status == 503:
            with pytest.raises(httpx.HTTPStatusError):
                await adapter.channel_history(
                    "tok", room_key(ROOM), api_base_url=BASE, limit=5, thread_id="$root"
                )
        else:
            assert (
                await adapter.channel_history(
                    "tok", room_key(ROOM), api_base_url=BASE, limit=5, thread_id="$root"
                )
                == []
            )

    @pytest.mark.parametrize("status", [200, 403, 503])
    async def test_room_history_is_chronological_and_refuses_remote_errors(
        self, adapter: MatrixAdapter, server: _Homeserver, status: int
    ) -> None:
        server.answer(
            "GET",
            _room_path(ROOM, "messages"),
            httpx.Response(
                status, json={"chunk": [_event("new"), _event("old"), {"type": "m.reaction"}]}
            ),
        )
        if status != 200:
            with pytest.raises(
                ChannelDirectoryUnsupported if status == 403 else httpx.HTTPStatusError
            ):
                await adapter.channel_history("tok", room_key(ROOM), api_base_url=BASE, limit=5)
        else:
            posts = await adapter.channel_history("tok", room_key(ROOM), api_base_url=BASE, limit=5)
            assert [p.text for p in posts] == ["old", "new"]

    async def test_account_is_cached_per_token_and_room_departure_resets_membership(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer("GET", f"{API}/account/whoami", httpx.Response(200, json={"user_id": OWN}))
        first = await adapter._account(BASE, "tok")
        assert await adapter._account(BASE, "tok") is first
        key = f"{BOT}:{ROOM}"
        adapter._direct.put(key, True)
        await adapter._on_sync(
            BOT, "tok", BASE, first, {"rooms": {"leave": {ROOM: {}}}}, backlog=False
        )
        assert adapter._direct.get(key) is None

    async def test_sync_token_rejection_stops_instead_of_retrying_forever(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET", f"{API}/sync", httpx.Response(401, json={"errcode": "M_UNKNOWN_TOKEN"})
        )
        with pytest.raises(ChannelNotConfigured):
            await adapter._sync(BASE, "tok", None)

    async def test_missing_and_failed_invitations_do_not_stop_other_rooms(
        self, adapter: MatrixAdapter, server: _Homeserver, caplog: pytest.LogCaptureFixture
    ) -> None:
        await adapter._on_invite(BOT, "tok", BASE, adapter._accounts[BOT], ROOM, {})
        server.answer("POST", _room_path(ROOM, "join"), httpx.Response(503))
        invitation = {
            "invite_state": {
                "events": [
                    {"type": "m.room.member", "state_key": OWN, "sender": USER, "content": {}}
                ]
            }
        }
        with patch("app.services.channels.ingress.invite_admitted", AsyncMock(return_value=True)):
            await adapter._on_invite(BOT, "tok", BASE, adapter._accounts[BOT], ROOM, invitation)
        assert "matrix_invite_unanswered" in caplog.text

    async def test_an_inaccessible_thread_root_never_counts_as_an_address(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        event = _event(**{"m.relates_to": {"rel_type": "m.thread", "event_id": "$root"}})
        server.answer("GET", _room_path(ROOM, "event", "$root"), httpx.Response(403))
        assert not await adapter._in_bot_thread(
            BOT, "tok", BASE, adapter._accounts[BOT], ROOM, event
        )

    async def test_gap_recovery_paginates_across_empty_pages_in_forward_order(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET",
            _room_path(ROOM, "messages"),
            httpx.Response(200, json={"chunk": [_event("first")], "end": "p1"}),
            httpx.Response(200, json={"chunk": [], "end": "p2"}),
            httpx.Response(200, json={"chunk": [_event("last")], "end": "stop"}),
        )
        events = [
            event
            async for event in adapter._gap(
                BOT, "tok", BASE, ROOM, {"prev_batch": "stop"}, since="durable"
            )
        ]
        assert [event["content"]["body"] for event in events] == ["first", "last"]
        assert len(server.calls) == 3

    async def test_gap_with_nonadvancing_continuation_is_not_acknowledged(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET",
            _room_path(ROOM, "messages"),
            httpx.Response(200, json={"chunk": [], "end": "same"}),
        )
        with pytest.raises(RuntimeError, match="did not advance"):
            [
                event
                async for event in adapter._gap(
                    BOT, "tok", BASE, ROOM, {"prev_batch": "stop"}, since="same"
                )
            ]

    async def test_empty_or_nonhuman_room_events_do_not_reach_admission(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET",
            _room_path(ROOM, "joined_members"),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}}}),
        )
        events = [{"type": "m.reaction"}, {**_event(), "sender": OWN}, _event("")]
        with patch("app.services.channels.ingress.admit_message", AsyncMock()) as admit:
            await adapter._on_room(
                BOT,
                "tok",
                BASE,
                adapter._accounts[BOT],
                ROOM,
                {"timeline": {"events": events}},
                backlog=False,
            )
            admit.assert_not_awaited()
        await adapter._on_room(BOT, "tok", BASE, adapter._accounts[BOT], ROOM, {}, backlog=False)

    async def test_chart_only_reply_uploads_a_file_without_an_empty_message(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        adapter.prepare_connection("unused", api_base_url=None, app_token=None)
        server.answer(
            "POST",
            "/_matrix/media/v3/upload",
            httpx.Response(200, json={"content_uri": "mxc://example.org/chart"}),
        )
        msg = OutgoingMessage(
            platform_chat_id=room_key(ROOM), text="", image_png=b"png", api_base_url=BASE
        )
        await adapter.send_message("tok", msg)
        assert len(server.sent()) == 1
        assert server.sent()[0][1]["msgtype"] == "m.image"
        assert "m.relates_to" not in server.sent()[0][1]

    async def test_text_in_thread_is_not_a_file(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer("GET", f"{API}/account/whoami", httpx.Response(200, json={"user_id": OWN}))
        server.answer(
            "GET",
            _relations(ROOM, "$root"),
            httpx.Response(200, json={"chunk": [_event("plain text")]}),
        )
        server.answer("GET", _room_path(ROOM, "event", "$root"), httpx.Response(404))
        assert (
            await adapter.thread_attachments(
                "tok", room_key(ROOM), thread_id="$root", api_base_url=BASE, limit=5
            )
            == []
        )

    async def test_encrypted_room_refuses_file_bytes_before_upload(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET",
            _room_path(ROOM, "state", "m.room.encryption", ""),
            httpx.Response(200, json={"algorithm": "m.megolm.v1.aes-sha2"}),
        )
        msg = OutgoingMessage(
            platform_chat_id=room_key(ROOM), text="", image_png=b"confidential", api_base_url=BASE
        )
        with pytest.raises(ChannelDirectoryUnsupported, match="encrypted"):
            await adapter.send_message("tok", msg)
        assert not any(method == "POST" for method, _, _ in server.calls)

    async def test_a_silent_third_member_invalidates_private_classification(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET",
            _room_path(DM, "joined_members"),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}}}),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}, "@third:example.org": {}}}),
        )
        assert await adapter._is_direct(BOT, "tok", BASE, DM)
        assert not await adapter._is_direct(BOT, "tok", BASE, DM)
        calls = len(server.calls)
        assert not await adapter._is_direct(BOT, "tok", BASE, DM)
        assert len(server.calls) == calls

    async def test_an_invite_omitting_encryption_is_checked_after_join_and_left(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET",
            _room_path(ROOM, "state", "m.room.encryption", ""),
            httpx.Response(200, json={"algorithm": "m.megolm.v1.aes-sha2"}),
        )
        invitation = {
            "invite_state": {
                "events": [
                    {
                        "type": "m.room.member",
                        "state_key": OWN,
                        "sender": USER,
                        "content": {"membership": "invite"},
                    }
                ]
            }
        }
        with patch("app.services.channels.ingress.invite_admitted", AsyncMock(return_value=True)):
            await adapter._on_invite(BOT, "tok", BASE, adapter._accounts[BOT], ROOM, invitation)
        calls = [(path, body) for method, path, body in server.calls if method == "POST"]
        assert calls[0][0] == _room_path(ROOM, "join")
        assert calls[1][0] == _room_path(ROOM, "leave")
        assert "encrypted" in calls[1][1]["reason"]

    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    @pytest.mark.parametrize(
        "target",
        [
            "http://127.0.0.1/private",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/private",
            "http://[::1]/private",
            "https://cdn.example.org/file",
        ],
    )
    async def test_media_redirects_are_refused_without_contacting_the_target(
        self, adapter: MatrixAdapter, server: _Homeserver, status: int, target: str
    ) -> None:
        path = "/_matrix/client/v1/media/download/example.org/file"
        server.answer("GET", path, httpx.Response(status, headers={"location": target}))
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.download_attachment(
                "tok", IncomingAttachment("file.txt", "text/plain", 0, BASE + path)
            )
        assert [(method, path) for method, path, _ in server.calls] == [("GET", path)]


@pytest.mark.security
class TestPrivateAudience:
    @pytest.mark.parametrize(
        "method", ["send", "begin", "update", "upload", "prompt", "reaction", "ack"]
    )
    @pytest.mark.parametrize(
        "members",
        [{OWN: {}, USER: {}, "@third:example.org": {}}, {OWN: {}, "@third:example.org": {}}],
    )
    async def test_a_changed_private_audience_refuses_all_output_paths(
        self, adapter: MatrixAdapter, server: _Homeserver, method: str, members: dict[str, object]
    ) -> None:
        key = room_key(ROOM, private_recipient=USER, server_url="https://matrix.example.org")
        chat = f"{key}:$question"
        server.answer("GET", f"{API}/account/whoami", httpx.Response(200, json={"user_id": OWN}))
        server.answer(
            "GET", _room_path(ROOM, "joined_members"), httpx.Response(200, json={"joined": members})
        )
        server.answer(
            "GET",
            _room_path(ROOM, "event", "$question"),
            httpx.Response(200, json={"room_id": ROOM}),
        )
        msg = _out("private result", chat)
        with (
            patch.object(matrix.sms_prompts, "reserve", AsyncMock(return_value=1)),
            pytest.raises(ChannelDirectoryUnsupported, match="original private audience"),
        ):
            if method == "send":
                await adapter.send_message("tok", msg)
            elif method == "begin":
                await adapter.begin_reply("tok", msg)
            elif method == "update":
                await adapter.update_reply("tok", msg, "$existing")
            elif method == "upload":
                msg.text = ""
                msg.attachments = [OutgoingAttachment("private.txt", b"private file")]
                await adapter.send_message("tok", msg)
            elif method == "prompt":
                await adapter.send_prompt(
                    "tok",
                    PromptMessage(
                        platform_chat_id=chat,
                        text="private question",
                        choices=[ChannelChoice("yes", "approved")],
                        api_base_url=BASE,
                        bot_id=BOT,
                    ),
                )
            elif method == "reaction":
                await adapter.react_to_message("tok", key, "$question", "eyes", api_base_url=BASE)
            else:
                incoming = adapter.parse_incoming(
                    {"room_id": ROOM, "event": _event(), "direct": True}, BOT
                )
                assert incoming is not None
                await adapter.acknowledge_message("tok", incoming, "eyes")
        assert server.sent() == [] and server.sent("m.reaction") == []
        assert not any(method == "POST" for method, _, _ in server.calls)

    async def test_an_edit_keeps_its_original_private_fence_even_if_the_caller_drops_it(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer("GET", f"{API}/account/whoami", httpx.Response(200, json={"user_id": OWN}))
        server.answer(
            "GET",
            _room_path(ROOM, "joined_members"),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}}}),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}, "@third:x": {}}}),
        )
        chat = f"{room_key(ROOM, private_recipient=USER, server_url='https://matrix.example.org')}:$question"
        handle = await adapter.begin_reply("tok", _out("working", chat))
        assert handle is not None
        before = len(server.sent())
        with pytest.raises(ChannelDirectoryUnsupported, match="private audience"):
            await adapter.update_reply("tok", _out("private result"), handle)
        assert len(server.sent()) == before

    @pytest.mark.parametrize(
        "other_base,other_token", [("https://other.example.org", "tok"), (BASE, "other-token")]
    )
    async def test_other_connections_cannot_replace_a_replys_private_audience(
        self, adapter: MatrixAdapter, server: _Homeserver, other_base: str, other_token: str
    ) -> None:
        server.answer("GET", f"{API}/account/whoami", httpx.Response(200, json={"user_id": OWN}))
        server.answer(
            "GET",
            _room_path(ROOM, "joined_members"),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}}}),
            httpx.Response(200, json={"joined": {OWN: {}, USER: {}, "@third:x": {}}}),
        )
        server.answer(
            "PUT",
            _room_path(ROOM, "send", "m.room.message") + "/*",
            httpx.Response(200, json={"event_id": "$collision"}),
        )
        private_chat = f"{room_key(ROOM, private_recipient=USER, server_url='https://matrix.example.org')}:$question"
        handle = await adapter.begin_reply("tok", _out("working", private_chat))
        untrusted = _out("another connection")
        untrusted.api_base_url = other_base
        assert await adapter.begin_reply(other_token, untrusted) == handle
        assert handle is not None
        sent = len(server.sent())
        with pytest.raises(ChannelDirectoryUnsupported, match="private audience"):
            await adapter.update_reply("tok", _out("private result"), handle)
        assert len(server.sent()) == sent

    @pytest.mark.parametrize("content", [{}, [], "upstream error"])
    async def test_present_but_malformed_encryption_state_never_allows_plaintext(
        self, adapter: MatrixAdapter, server: _Homeserver, content: object
    ) -> None:
        server.answer(
            "GET",
            _room_path(ROOM, "state", "m.room.encryption", ""),
            httpx.Response(200, json=content),
        )
        with pytest.raises(ChannelDirectoryUnsupported, match="encrypted"):
            await adapter.send_message("tok", _out("private result"))
        assert server.sent() == []

    async def test_forbidden_encryption_state_does_not_allow_plaintext(
        self, adapter: MatrixAdapter, server: _Homeserver
    ) -> None:
        server.answer(
            "GET", _room_path(ROOM, "state", "m.room.encryption", ""), httpx.Response(403)
        )
        with pytest.raises(ChannelDirectoryUnsupported, match="not in"):
            await adapter.send_message("tok", _out("private result"))
        assert server.sent() == []


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("file", [False, True])
@pytest.mark.security
async def test_a_queued_destination_cannot_send_on_another_homeserver(
    adapter: MatrixAdapter, server: _Homeserver, private: bool, file: bool
) -> None:
    key = room_key(ROOM, server_url=BASE, private_recipient=USER if private else None)
    msg = _out("" if file else "confidential answer", f"{key}:$question")
    msg.api_base_url = "https://other.example.org"
    if file:
        msg.attachments = [OutgoingAttachment("private.txt", b"confidential file")]
    with pytest.raises(ChannelDirectoryUnsupported, match="homeserver"):
        await adapter.send_message("tok", msg)
    assert server.calls == []


@pytest.mark.parametrize(
    "operation", ["member", "members", "details", "history", "files", "reaction"]
)
@pytest.mark.security
async def test_directory_calls_never_reinterpret_a_room_on_another_server(
    adapter: MatrixAdapter, server: _Homeserver, operation: str
) -> None:
    key = room_key(ROOM, server_url="https://original.example.org")
    with pytest.raises(ChannelDirectoryUnsupported, match="homeserver"):
        if operation == "member":
            await adapter.is_channel_member("tok", key, USER, api_base_url=BASE)
        elif operation == "members":
            await adapter.channel_members("tok", key, api_base_url=BASE, limit=10)
        elif operation == "details":
            await adapter.channel_details("tok", key, api_base_url=BASE)
        elif operation == "history":
            await adapter.channel_history("tok", key, api_base_url=BASE, limit=10)
        elif operation == "files":
            await adapter.thread_attachments(
                "tok", key, thread_id="$root", api_base_url=BASE, limit=10
            )
        else:
            await adapter.react_to_message("tok", key, "$question", "eyes", api_base_url=BASE)
    assert server.calls == []


@pytest.mark.security
def test_an_old_sync_stream_cannot_assert_the_new_connections_authority(
    adapter: MatrixAdapter,
) -> None:
    adapter.prepare_connection(BOT, api_base_url="https://other.example.org", app_token=None)
    assert (
        adapter.parse_incoming(
            {"room_id": ROOM, "event": _event(), "server_url": BASE, "direct": True}, BOT
        )
        is None
    )


@pytest.mark.parametrize("upload", [False, True])
@pytest.mark.parametrize("changed", ["members", "encryption"])
@pytest.mark.security
async def test_rate_limit_retries_revalidate_private_disclosure(
    adapter: MatrixAdapter, server: _Homeserver, upload: bool, changed: str
) -> None:
    transaction = uuid4()
    server.answer("GET", f"{API}/account/whoami", httpx.Response(200, json={"user_id": OWN}))
    server.answer(
        "GET",
        _room_path(ROOM, "joined_members"),
        httpx.Response(200, json={"joined": {OWN: {}, USER: {}}}),
        httpx.Response(
            200,
            json={
                "joined": {
                    OWN: {},
                    USER: {},
                    **({"@third:domain": {}} if changed == "members" else {}),
                }
            },
        ),
    )
    server.answer(
        "GET",
        _room_path(ROOM, "state", "m.room.encryption", ""),
        httpx.Response(404),
        httpx.Response(200 if changed == "encryption" else 404, json={}),
    )
    path = (
        "/_matrix/media/v3/upload"
        if upload
        else _room_path(ROOM, "send", "m.room.message", transaction.hex)
    )
    server.answer(
        "POST" if upload else "PUT",
        path,
        httpx.Response(429, json={"retry_after_ms": 0}),
        httpx.Response(
            200, json={"event_id": "$must-not-send", "content_uri": "mxc://domain/must-not-upload"}
        ),
    )
    key = room_key(ROOM, server_url=BASE, private_recipient=USER)
    msg = _out("" if upload else "private result", f"{key}:$question")
    if upload:
        msg.attachments = [OutgoingAttachment("private.txt", b"private result")]
    with (
        patch.object(matrix, "uuid4", return_value=transaction),
        pytest.raises(ChannelDirectoryUnsupported),
    ):
        await adapter.send_message("tok", msg)
    assert len([method for method, _, _ in server.calls if method in {"PUT", "POST"}]) == 1


@pytest.mark.parametrize("label", ["a" * 1000, "\x00bad", "\ud800bad", None])
def test_display_labels_always_fit_the_identity_storage_contract(
    adapter: MatrixAdapter, label: str | None
) -> None:
    incoming = adapter.parse_incoming(
        {"room_id": ROOM, "event": _event(), "direct": True, "display_name": label}, BOT
    )
    assert incoming is not None
    assert incoming.platform_display_name == (
        "a" * 255 if label and label.startswith("a") else None
    )


async def test_thread_addressing_cache_does_not_cross_server_or_account_changes(
    adapter: MatrixAdapter, server: _Homeserver
) -> None:
    event = _event("reply", **{"m.relates_to": {"rel_type": "m.thread", "event_id": "$root"}})
    root = {**_event(), "event_id": "$root"}
    server.answer(
        "GET",
        _room_path(ROOM, "event", "$root"),
        httpx.Response(200, json={**root, "sender": OWN}),
        httpx.Response(200, json=root),
        httpx.Response(200, json=root),
    )
    account = _Account(user_id=OWN, display_name="Agent")
    assert await adapter._in_bot_thread(BOT, "tok", BASE, account, ROOM, event)
    assert not await adapter._in_bot_thread(
        BOT, "tok", "https://other.example.org", account, ROOM, event
    )
    assert not await adapter._in_bot_thread(BOT, "another-token", BASE, account, ROOM, event)


async def test_sender_labels_from_another_homeserver_are_not_reused(adapter: MatrixAdapter) -> None:
    state = [
        {
            "type": "m.room.member",
            "state_key": USER,
            "content": {"displayname": "Alice on first server"},
        }
    ]
    joined = {"state": {"events": state}, "timeline": {"events": [_event()]}}
    batch = {"rooms": {"join": {ROOM: joined}}}
    admitted = AsyncMock()
    account = _Account(user_id=OWN, display_name="Agent")
    with patch("app.services.channels.ingress.admit_message", admitted):
        await adapter._on_sync(BOT, "tok", BASE, account, batch, backlog=False)
        other_base = "https://other.example.org"
        adapter.prepare_connection(BOT, api_base_url=other_base, app_token=None)
        joined["state"] = {"events": []}
        await adapter._on_sync(BOT, "tok", other_base, account, batch, backlog=False)
    assert [call.args[0].platform_display_name for call in admitted.await_args_list] == [
        "Alice on first server",
        None,
    ]
