"""The Matrix adapter: reading `/sync`, and answering over the Client-Server API (#2081).

The homeserver is an `httpx.MockTransport` that records every call, so what is
asserted is the request the homeserver would receive: the room and thread it
goes to, whether it can notify anybody, and what an edit or a reaction is.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import httpx
import pytest

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


def _room_path(room: str, *parts: str) -> str:
    """A room's path as the adapter writes it, every segment percent-encoded."""
    return f"{API}/rooms/" + "/".join(quote(part, safe="") for part in (room, *parts))


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
        queued = self.routes.get((request.method, path))
        if queued:
            return queued.pop(0) if len(queued) > 1 else queued[0]
        for (method, prefix), responses in self.routes.items():
            if method == request.method and prefix.endswith("*") and path.startswith(prefix[:-1]):
                return responses[0]
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
        assert incoming.platform_chat_id == f"{room_key(ROOM)}:$question"
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
        assert incoming.platform_chat_id == f"{room_key(ROOM)}:$root"
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
        with patch.object(MatrixAdapter, "_invite_admitted", check):
            await adapter._on_sync(
                BOT,
                "tok",
                BASE,
                adapter._accounts[BOT],
                {"next_batch": "s1", "rooms": {"invite": {ROOM: invite}}},
                backlog=True,
            )
        assert check.await_args.args[1:] == (USER, ROOM)
        assert check.await_args.kwargs == {"direct": True}
        assert ("POST", _room_path(ROOM, action), {}) in server.calls

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
            patch.object(MatrixAdapter, "_bot_access", AsyncMock(return_value=(BASE, "tok"))),
        ):
            await adapter.settle_prompt("tok", press, "Approved")
        assert settle.await_args.kwargs == {"platform": "matrix"}
        assert server.sent()[0][1]["body"] == "Approved"


class TestReactions:
    async def test_a_question_is_acknowledged_with_the_emoji(
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
        with patch.object(MatrixAdapter, "_bot_access", AsyncMock(return_value=(BASE, "tok"))):
            await adapter.acknowledge_message("tok", incoming, "eyes")
        [(_, body)] = server.sent("m.reaction")
        assert body == {
            "m.relates_to": {"rel_type": "m.annotation", "event_id": "$question", "key": "👀"}
        }

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


class TestHistoryAndFiles:
    async def test_a_threads_history_is_its_root_and_replies_as_edited(
        self, adapter: MatrixAdapter, server: _Homeserver
    ):
        server.answer(
            "GET",
            _room_path(ROOM, "relations", "$root", "m.thread"),
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
            _room_path(ROOM, "relations", "$root", "m.thread"),
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
