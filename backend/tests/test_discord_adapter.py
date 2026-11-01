"""The Discord adapter: reading the Gateway, and answering over the REST API (#2079).

Discord's REST API is an `httpx.MockTransport` that records every call, so what
is asserted is the request Discord would receive: the channel or thread it goes
to, whether it can ping anybody, and what a button or a thread looks like.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from opentelemetry.instrumentation.utils import is_instrumentation_enabled
from pydantic_ai import Agent
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from app.agents.capabilities.guardrails import GuardrailsConfig
from app.core.memory_keys import room_owner_key
from app.services.channels import discord
from app.services.channels.base import (
    ChannelChoice,
    FeedbackComment,
    IncomingAttachment,
    IncomingMessage,
    IncomingPress,
    OutgoingAttachment,
    OutgoingMessage,
    PromptMessage,
    memory_room_key,
)
from app.services.channels.discord import DiscordAdapter, _Channel, _Reply, _Session
from app.services.channels.discord_protocol import VIEW_CHANNEL
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.live_reply import LiveReply, channel_stream
from app.services.file_upload import FileUploadService
from tests.test_guardrails_capability import _KEY_IN_PIECES, SECRET, _agent, _streams

pytestmark = pytest.mark.anyio

BOT = "bot-1"
OWN = "900"
APP = "800"
GUILD = "100"
CHANNEL = "200"
MESSAGE = "300"
THREAD = "400"
USER = "500"


class _Discord:
    """Discord's REST API, recording each call and answering from `routes`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.traced: list[tuple[str, bool]] = []
        self.routes: dict[tuple[str, str], list[httpx.Response]] = {}
        self._next = 1000

    def answer(self, method: str, path: str, *responses: httpx.Response) -> None:
        self.routes[(method, path)] = list(responses)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v10")
        body: Any = None
        if request.content:
            if request.headers.get("content-type", "").startswith("multipart"):
                body = request.content
            else:
                body = json.loads(request.content)
        self.calls.append((request.method, path, body))
        self.traced.append((path, is_instrumentation_enabled()))
        queued = self.routes.get((request.method, path))
        if queued:
            return queued.pop(0) if len(queued) > 1 else queued[0]
        self._next += 1
        return httpx.Response(200, json={"id": str(self._next)})

    def posted(self, path: str) -> list[Any]:
        return [body for method, called, body in self.calls if method == "POST" and called == path]


@pytest.fixture
def api() -> _Discord:
    return _Discord()


@pytest.fixture
def adapter(api: _Discord) -> DiscordAdapter:
    built = DiscordAdapter()
    built._http = httpx.AsyncClient(transport=httpx.MockTransport(api.handle))
    built._own_ids[BOT] = OWN
    built._app_ids[BOT] = APP
    built._tokens[BOT] = "tok"
    return built


def _reply(adapter: DiscordAdapter, handle: str) -> _Reply:
    reply = adapter._replies.get(handle)
    assert reply is not None
    return reply


def _message(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": MESSAGE,
        "type": 0,
        "channel_id": CHANNEL,
        "guild_id": GUILD,
        "content": f"<@{OWN}> what is the refund window?",
        "author": {"id": USER, "username": "ada", "global_name": "Ada"},
        "mentions": [{"id": OWN}],
        "member": {"nick": "Ada L."},
    }
    payload.update(overrides)
    return payload


class TestReading:
    def test_a_mention_in_a_channel_is_a_question_keyed_on_its_own_thread(
        self, adapter: DiscordAdapter
    ):
        incoming = adapter.parse_incoming(_message(), BOT)
        assert incoming is not None
        assert incoming.platform_chat_id == f"{CHANNEL}:{MESSAGE}"
        assert incoming.chat_type == "group"
        assert incoming.addressed is True
        assert incoming.text == "what is the refund window?"
        assert incoming.platform_display_name == "Ada L."
        assert adapter._thread_names.get(f"{CHANNEL}:{MESSAGE}") == "what is the refund window?"

    def test_a_message_naming_nobody_is_overheard(self, adapter: DiscordAdapter):
        incoming = adapter.parse_incoming(_message(content="lunch?", mentions=[]), BOT)
        assert incoming is not None
        assert incoming.addressed is False

    @pytest.mark.parametrize(("role", "addressed"), [("r1", True), ("r2", False)])
    async def test_mentioning_the_bot_s_own_role_addresses_it(
        self, adapter: DiscordAdapter, role: str, addressed: bool
    ):
        """Discord offers the bot's managed role beside the bot when its name is typed."""
        await adapter._on_dispatch(
            "GUILD_CREATE",
            {"id": GUILD, "roles": [{"id": "r1", "tags": {"bot_id": OWN}}, {"id": "r2"}]},
            BOT,
            "tok",
            _Session(guilds={GUILD}),
        )
        incoming = adapter.parse_incoming(
            _message(content=f"<@&{role}> refund window?", mentions=[], mention_roles=[role]),
            BOT,
        )
        assert incoming is not None
        assert incoming.addressed is addressed
        assert (incoming.text == "refund window?") is addressed

    def test_a_reply_to_the_bot_addresses_it(self, adapter: DiscordAdapter):
        incoming = adapter.parse_incoming(
            _message(
                content="and for EU?", mentions=[], referenced_message={"author": {"id": OWN}}
            ),
            BOT,
        )
        assert incoming is not None
        assert incoming.addressed is True

    @pytest.mark.parametrize(
        ("replied", "root"),
        [
            (
                {"id": "answer", "author": {"id": OWN}, "message_reference": {"message_id": "q"}},
                "q",
            ),
            ({"id": "posted", "author": {"id": OWN}}, "posted"),
            ({"id": "other", "author": {"id": "someone"}}, MESSAGE),
        ],
    )
    def test_a_reply_to_the_bot_continues_the_question_it_answered(
        self, adapter: DiscordAdapter, replied: dict[str, Any], root: str
    ):
        incoming = adapter.parse_incoming(
            _message(content="and for EU?", type=19, referenced_message=replied), BOT
        )
        assert incoming is not None
        assert incoming.platform_chat_id == f"{CHANNEL}:{root}"

    @pytest.mark.parametrize("pinged", [True, False])
    def test_an_everyone_ping_is_a_broadcast_only_when_discord_sent_it(
        self, adapter: DiscordAdapter, pinged: bool
    ):
        """Whether it starts a run is the bot's `respond_to_broadcasts`, decided by the router."""
        incoming = adapter.parse_incoming(
            _message(content="@everyone standup moved", mentions=[], mention_everyone=pinged),
            BOT,
        )
        assert incoming is not None
        assert incoming.broadcast_mention is pinged
        assert incoming.addressed is False

    def test_a_message_in_a_thread_the_bot_opened_continues_it(self, adapter: DiscordAdapter):
        adapter._channels.put(THREAD, _Channel(kind=11, parent_id=CHANNEL, owner_id=OWN))
        incoming = adapter.parse_incoming(
            _message(channel_id=THREAD, content="and for EU?", mentions=[]), BOT
        )
        assert incoming is not None
        assert incoming.platform_chat_id == f"{CHANNEL}:{THREAD}"
        assert incoming.addressed is True
        assert THREAD in adapter._threads

    def test_a_private_thread_is_a_room_of_its_own(self, adapter: DiscordAdapter):
        adapter._channels.put(THREAD, _Channel(kind=12, parent_id=CHANNEL, owner_id=USER))
        incoming = adapter.parse_incoming(_message(channel_id=THREAD), BOT)
        assert incoming is not None
        # Its own channel and its own thread, so a bot brought in partway has a
        # thread to read the earlier messages of.
        assert incoming.platform_chat_id == f"{THREAD}:{THREAD}"
        assert memory_room_key("discord", incoming.platform_chat_id, "group") == (
            room_owner_key("discord", THREAD)
        )

    def test_a_direct_message_is_one_conversation_and_always_addressed(
        self, adapter: DiscordAdapter
    ):
        incoming = adapter.parse_incoming(
            _message(guild_id=None, channel_id="dm", content="hi", mentions=[]), BOT
        )
        assert incoming is not None
        assert incoming.platform_chat_id == "dm"
        assert incoming.chat_type == "private"
        assert incoming.addressed is True

    def test_before_ready_a_server_message_is_not_judged(self, adapter: DiscordAdapter):
        adapter._own_ids.clear()
        incoming = adapter.parse_incoming(_message(), BOT)
        assert incoming is not None
        assert incoming.addressed is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"author": {"id": OWN}},
            {"author": {"id": "7", "bot": True}},
            {"webhook_id": "9"},
            {"type": 7},
            {"content": f"<@{OWN}>"},
        ],
    )
    def test_the_bot_itself_other_bots_and_system_messages_are_not_heard(
        self, adapter: DiscordAdapter, overrides: dict[str, Any]
    ):
        assert adapter.parse_incoming(_message(**overrides), BOT) is None

    def test_a_file_with_no_text_is_still_a_message(self, adapter: DiscordAdapter):
        incoming = adapter.parse_incoming(
            _message(
                content="",
                attachments=[
                    {
                        "filename": "q.pdf",
                        "content_type": "application/pdf",
                        "size": 5,
                        "url": "https://cdn.discordapp.com/q",
                    },
                    {"filename": "no-url"},
                ],
            ),
            BOT,
        )
        assert incoming is not None
        assert [item.filename for item in incoming.attachments] == ["q.pdf"]

    def test_a_pasted_image_discord_mislabels_is_typed_by_its_name(self, adapter: DiscordAdapter):
        """A clipboard paste arrives as `image.png`, PNG bytes, `image/webp`.

        Upload validation refused that pairing as a type contradicting its
        extension, so every pasted screenshot was turned away.
        """
        incoming = adapter.parse_incoming(
            _message(
                attachments=[
                    {
                        "filename": "image.png",
                        "content_type": "image/webp",
                        "size": 1324,
                        "url": "https://cdn.discordapp.com/image.png",
                    }
                ]
            ),
            BOT,
        )

        assert incoming is not None
        (pasted,) = incoming.attachments
        assert pasted.mime_type == "image/png"
        assert FileUploadService.validate_upload(
            pasted.mime_type, pasted.size, pasted.filename
        ) == (
            True,
            None,
        )


class TestPosting:
    async def test_the_first_answer_opens_a_thread_on_the_question(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        adapter._thread_names.put(f"{CHANNEL}:{MESSAGE}", "refunds")
        await adapter.send_message(
            "tok", OutgoingMessage(f"{CHANNEL}:{MESSAGE}", "@everyone 30 days")
        )

        assert api.posted(f"/channels/{CHANNEL}/messages/{MESSAGE}/threads") == [
            {"name": "refunds", "auto_archive_duration": 1440}
        ]
        [body] = api.posted(f"/channels/{MESSAGE}/messages")
        assert body["content"] == "@everyone 30 days"
        assert body["allowed_mentions"] == {"parse": []}

    async def test_a_thread_already_open_on_the_message_is_used(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer(
            "POST",
            f"/channels/{CHANNEL}/messages/{MESSAGE}/threads",
            httpx.Response(400, json={"code": 160004}),
        )
        await adapter.send_message("tok", OutgoingMessage(f"{CHANNEL}:{MESSAGE}", "hi"))
        await adapter.send_message("tok", OutgoingMessage(f"{CHANNEL}:{MESSAGE}", "again"))

        assert len(api.posted(f"/channels/{CHANNEL}/messages/{MESSAGE}/threads")) == 1
        assert len(api.posted(f"/channels/{MESSAGE}/messages")) == 2

    async def test_a_thread_this_process_has_not_seen_is_found_rather_than_left(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer(
            "GET",
            f"/channels/{THREAD}",
            httpx.Response(200, json={"id": THREAD, "type": 11, "parent_id": CHANNEL}),
        )
        await adapter.send_message("tok", OutgoingMessage(f"{CHANNEL}:{THREAD}", "approved"))

        assert api.posted(f"/channels/{CHANNEL}/messages/{THREAD}/threads") == []
        assert api.posted(f"/channels/{CHANNEL}/messages") == []
        [body] = api.posted(f"/channels/{THREAD}/messages")
        assert body["content"] == "approved"

    async def test_where_no_thread_may_be_opened_the_answer_replies_in_the_channel(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer(
            "POST",
            f"/channels/{CHANNEL}/messages/{MESSAGE}/threads",
            httpx.Response(403, text="no"),
        )
        await adapter.send_message("tok", OutgoingMessage(f"{CHANNEL}:{MESSAGE}", "hi"))
        await adapter.send_message("tok", OutgoingMessage(f"{CHANNEL}:{MESSAGE}", "again"))

        assert len(api.posted(f"/channels/{CHANNEL}/messages/{MESSAGE}/threads")) == 1
        first, second = api.posted(f"/channels/{CHANNEL}/messages")
        assert first["message_reference"]["message_id"] == MESSAGE
        assert second["message_reference"]["message_id"] == MESSAGE

    async def test_where_no_thread_may_be_opened_every_part_of_a_long_answer_names_the_question(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer(
            "POST",
            f"/channels/{CHANNEL}/messages/{MESSAGE}/threads",
            httpx.Response(403, text="no"),
        )
        chat = f"{CHANNEL}:{MESSAGE}"
        await adapter.send_message("tok", OutgoingMessage(chat, "a" * 2500))
        handle = await adapter.begin_reply("tok", OutgoingMessage(chat, ""))
        assert handle is not None
        await adapter.update_reply("tok", OutgoingMessage(chat, "b" * 2500), handle)
        adapter._replies = discord.Recent(10)
        await adapter.update_reply("tok", OutgoingMessage(chat, "c" * 4500), handle)

        posted = api.posted(f"/channels/{CHANNEL}/messages")
        assert len(posted) == 6
        assert {body["message_reference"]["message_id"] for body in posted} == {MESSAGE}

    async def test_a_long_answer_is_several_messages_with_files_on_the_last(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        await adapter.send_message(
            "tok",
            OutgoingMessage(
                "dm",
                "a" * 1500 + "\n" + "b" * 1000,
                image_png=b"png",
                attachments=[OutgoingAttachment("r.csv", b"x,y", "text/csv")],
            ),
        )
        first, last = api.posted("/channels/dm/messages")
        assert first["content"] == "a" * 1500
        assert isinstance(last, bytes)
        assert b'name="files[0]"; filename="chart.png"' in last
        assert b'name="files[1]"; filename="r.csv"' in last
        assert b"b" * 1000 in last

    async def test_a_file_sent_on_its_own_is_posted_without_text(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        """What `send_channel_file` sends: an attachment and no words."""
        await adapter.send_message(
            "tok",
            OutgoingMessage(
                "dm", "", attachments=[OutgoingAttachment("r.csv", b"x,y", "text/csv")]
            ),
        )
        (posted,) = api.posted("/channels/dm/messages")
        assert b'name="files[0]"; filename="r.csv"' in posted

    async def test_an_empty_message_with_nothing_attached_posts_nothing(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        await adapter.send_message("tok", OutgoingMessage("dm", ""))
        assert api.calls == []

    async def test_a_rate_limit_is_waited_out(self, adapter: DiscordAdapter, api: _Discord):
        api.answer(
            "POST",
            "/channels/dm/messages",
            httpx.Response(429, json={"retry_after": 0.01}),
            httpx.Response(200, json={"id": "1"}),
        )
        await adapter.send_message("tok", OutgoingMessage("dm", "hi"))
        assert len(api.posted("/channels/dm/messages")) == 2

    async def test_a_rate_limit_that_persists_fails_the_post(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer("POST", "/channels/dm/messages", httpx.Response(429, json={"retry_after": 0}))
        with pytest.raises(httpx.HTTPStatusError):
            await adapter.send_message("tok", OutgoingMessage("dm", "hi"))
        assert len(api.posted("/channels/dm/messages")) == 3


class TestLiveReply:
    async def test_an_answer_grows_past_one_message_and_shrinks_back(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        handle = await adapter.begin_reply("tok", OutgoingMessage("dm", ""))
        assert handle is not None
        long = "a" * 1500 + "\n" + "b" * 1000

        await adapter.update_reply("tok", OutgoingMessage("dm", long), handle)
        await adapter.update_reply("tok", OutgoingMessage("dm", long), handle)
        await adapter.update_reply("tok", OutgoingMessage("dm", "short"), handle)

        edits = [body["content"] for method, path, body in api.calls if method == "PATCH"]
        assert edits == ["a" * 1500, "short"]
        posted = api.posted("/channels/dm/messages")
        assert [body["content"] for body in posted] == ["…", "b" * 1000]
        deleted = [path for method, path, _ in api.calls if method == "DELETE"]
        assert len(deleted) == 1

    async def test_a_reply_this_process_did_not_open_is_still_edited(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        adapter._threads.put(THREAD, True)
        await adapter.update_reply("tok", OutgoingMessage(f"{CHANNEL}:{THREAD}", "done"), "77")
        assert ("PATCH", f"/channels/{THREAD}/messages/77") in [(m, p) for m, p, _ in api.calls]

    async def test_a_deleted_overflow_message_is_not_an_error(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        handle = await adapter.begin_reply("tok", OutgoingMessage("dm", "x"))
        assert handle is not None
        await adapter.update_reply("tok", OutgoingMessage("dm", "a" * 2500), handle)
        overflow = _reply(adapter, handle).ids[-1]
        api.answer("DELETE", f"/channels/dm/messages/{overflow}", httpx.Response(404))
        await adapter.update_reply("tok", OutgoingMessage("dm", "short"), handle)
        assert _reply(adapter, handle).ids == [handle]

    async def test_typing_is_shown_where_the_answer_will_be(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        adapter._threads.put(THREAD, True)
        await adapter.typing(BOT, OutgoingMessage(f"{CHANNEL}:{THREAD}", ""))
        await adapter.typing(BOT, OutgoingMessage(f"{CHANNEL}:{MESSAGE}", ""))
        await adapter.typing("unknown", OutgoingMessage("dm", ""))
        assert [path for _, path, _ in api.calls] == [
            f"/channels/{THREAD}/typing",
            f"/channels/{CHANNEL}/typing",
        ]

    @pytest.mark.security
    async def test_a_streamed_answer_never_shows_discord_the_secret_it_redacts(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        """#1900 on Discord: the answer streams by editing, and every edit is screened.

        The key arrives split across deltas, and every delta is pushed - the
        clock is stepped past the edit interval each time - so a single
        unscreened delta would reach Discord.
        """
        agent: Agent = _agent(GuardrailsConfig(redact_secrets_out=True), _streams(_KEY_IN_PIECES))
        handle = await adapter.begin_reply("tok", OutgoingMessage("dm", "…"))
        assert handle is not None
        ticks = iter(range(0, 1000, 5))

        async def push(text: str) -> None:
            await adapter.update_reply("tok", OutgoingMessage("dm", text), handle)

        reply = LiveReply(push, now=lambda: float(next(ticks)))
        async with agent.iter("go") as run:
            await channel_stream(reply)(run)
        await push(reply.text)

        sent = json.dumps([body for _, _, body in api.calls])
        assert SECRET not in sent
        assert "[redacted:anthropic_key]" in sent


class TestPrompts:
    async def test_an_approval_is_buttons_and_a_press_takes_them_off(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        await adapter.send_prompt(
            "tok",
            PromptMessage(
                "dm",
                "x" * 2100,
                [
                    ChannelChoice("Approve", "aos:p:0", "primary"),
                    ChannelChoice("Reject", "aos:p:1", "danger"),
                ],
            ),
        )
        first, last = api.posted("/channels/dm/messages")
        assert "components" not in first
        assert [b["custom_id"] for b in last["components"][0]["components"]] == [
            "aos:p:0",
            "aos:p:1",
        ]

        await adapter.settle_prompt(
            "tok",
            IncomingPress(
                "discord", BOT, USER, "dm", "aos:p:0", message_id="m1", prompt_text="Run it?"
            ),
            "Approved",
        )
        [(_, path, body)] = [call for call in api.calls if call[0] == "PATCH"]
        assert path == "/channels/dm/messages/m1"
        assert body["content"] == "Run it?\n**Approved**"
        assert body["components"] == []

    async def test_a_press_on_a_message_it_cannot_name_is_left_alone(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        await adapter.settle_prompt("tok", IncomingPress("discord", BOT, USER, "dm", "v"), "x")
        await adapter.acknowledge("tok", IncomingPress("discord", BOT, USER, "dm", "v"))
        await adapter.settle_prompt(
            "tok", IncomingPress("discord", BOT, USER, "dm", "v", message_id="m"), "Done"
        )
        [(_, _, body)] = api.calls
        assert body["content"] == "**Done**"

    async def test_thumbs_go_under_the_answer_s_last_message(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        handle = await adapter.begin_reply("tok", OutgoingMessage("dm", "x"))
        assert handle is not None
        await adapter.update_reply("tok", OutgoingMessage("dm", "a" * 2500), handle)
        last = _reply(adapter, handle).ids[-1]
        await adapter.offer_feedback("tok", OutgoingMessage("dm", ""), handle, "run-1", bot_id=BOT)
        method, path, body = api.calls[-1]
        assert (method, path) == ("PATCH", f"/channels/dm/messages/{last}")
        ids = [button["custom_id"] for button in body["components"][0]["components"]]
        assert ids == ["aosfb:run-1:+", "aosfb:run-1:-"]

        await adapter.offer_feedback("tok", OutgoingMessage("dm", ""), "other", "run-1", bot_id=BOT)
        assert api.calls[-1][1] == "/channels/dm/messages/other"

    async def test_a_thumbs_up_is_thanked_privately(self, adapter: DiscordAdapter, api: _Discord):
        press = IncomingPress("discord", BOT, USER, "dm", "aosfb:r:+", ack_id="itok")
        await adapter.settle_feedback("tok", press, True)
        await adapter.settle_feedback("tok", press, False)
        assert api.posted(f"/webhooks/{APP}/itok") == [
            {"content": "Thanks for rating this answer.", "flags": 64}
        ]


@pytest.fixture(autouse=True)
def _admitted() -> Iterator[None]:
    """`/ask` asks the router whether the sender may be published; here they may."""
    with patch.object(discord, "refusal_before_publishing", AsyncMock(return_value=None)):
        yield


@pytest.fixture
def spawned() -> Iterator[list[Any]]:
    """What the adapter handed to background work: the message, press or comment routed."""
    seen: list[Any] = []

    def spawn(routed: Any, *, name: str) -> None:
        seen.append(routed)

    with (
        patch.object(discord, "spawn", spawn),
        patch.object(discord, "process_channel_event", lambda incoming: incoming),
        patch.object(discord, "process_channel_press", lambda press: press),
        patch.object(discord, "process_feedback_comment", lambda comment: comment),
    ):
        yield seen


class TestInteractions:
    async def test_ask_posts_the_question_and_threads_the_answer_under_it(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        api.answer(
            "POST",
            "/interactions/i1/itok/callback",
            httpx.Response(200, json={"resource": {"message": {"id": "q1"}}}),
        )
        await adapter._on_interaction(
            {
                "type": 2,
                "id": "i1",
                "token": "itok",
                "guild_id": GUILD,
                "channel": {"id": CHANNEL, "type": 0},
                "member": {"user": {"id": USER, "username": "ada"}},
                "data": {"name": "ask", "type": 1, "options": [{"value": "refund window?"}]},
            },
            BOT,
        )
        [incoming] = spawned
        assert isinstance(incoming, IncomingMessage)
        assert incoming.platform_chat_id == f"{CHANNEL}:q1"
        assert incoming.text == "refund window?"
        assert incoming.addressed is True
        assert adapter._thread_names.get(f"{CHANNEL}:q1") == "refund window?"
        [body] = api.posted("/interactions/i1/itok/callback")
        assert body["data"]["allowed_mentions"] == {"parse": []}

    async def test_a_channel_command_is_answered_privately_in_its_own_response(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        await adapter._on_interaction(
            {
                "type": 2,
                "id": "i2",
                "token": "itok",
                "channel_id": "dm",
                "user": {"id": USER},
                "data": {"name": "help", "type": 1},
            },
            BOT,
        )
        [incoming] = spawned
        assert incoming.text == "/help"
        assert incoming.chat_type == "private"
        assert api.posted("/interactions/i2/itok/callback") == [{"type": 5, "data": {"flags": 64}}]

        await adapter.send_message(
            "tok", OutgoingMessage("dm", "a" * 2500, reply_to_message_id="i2")
        )
        assert [(m, p) for m, p, _ in api.calls[1:]] == [
            ("PATCH", f"/webhooks/{APP}/itok/messages/@original"),
            ("POST", f"/webhooks/{APP}/itok"),
        ]

    async def test_ask_about_a_message_quotes_it_in_a_thread_on_it(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        await adapter._on_interaction(
            {
                "type": 2,
                "id": "i3",
                "token": "itok",
                "guild_id": GUILD,
                "channel_id": CHANNEL,
                "member": {"user": {"id": USER}},
                "data": {
                    "name": "Ask the agent",
                    "type": 3,
                    "target_id": MESSAGE,
                    "resolved": {"messages": {MESSAGE: {"content": "deploy failed\nexit 1"}}},
                },
            },
            BOT,
        )
        [incoming] = spawned
        assert incoming.platform_chat_id == f"{CHANNEL}:{MESSAGE}"
        assert incoming.text == "Help me with this message:\n> deploy failed\n> exit 1"
        assert adapter._thread_names.get(f"{CHANNEL}:{MESSAGE}") == "deploy failed"
        assert incoming.attachments == []

    async def test_ask_about_a_message_is_refused_privately_and_answered_in_a_thread(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        """A refusal must not open a public thread on a colleague's message."""
        ask = {
            "type": 2,
            "id": "i3",
            "token": "itok",
            "guild_id": GUILD,
            "channel_id": CHANNEL,
            "member": {"user": {"id": USER}},
            "data": {
                "name": "Ask the agent",
                "type": 3,
                "target_id": MESSAGE,
                "resolved": {"messages": {MESSAGE: {"content": "deploy failed"}}},
            },
        }
        await adapter._on_interaction(ask, BOT)
        chat = f"{CHANNEL}:{MESSAGE}"
        await adapter.send_message(
            "tok", OutgoingMessage(chat, "You are not authorised.", reply_to_message_id="i3")
        )
        assert [(m, p) for m, p, _ in api.calls[1:]] == [
            ("PATCH", f"/webhooks/{APP}/itok/messages/@original")
        ]

        api.calls.clear()
        await adapter.begin_reply("tok", OutgoingMessage(chat, "…", reply_to_message_id="i3"))
        await adapter.send_message("tok", OutgoingMessage(chat, "", reply_to_message_id="i3"))
        assert f"/channels/{CHANNEL}/messages/{MESSAGE}/threads" in [p for _, p, _ in api.calls]
        assert not [p for _, p, _ in api.calls if p.startswith("/webhooks/")]

    @pytest.mark.parametrize(
        ("channel", "key"),
        [
            ({"id": CHANNEL, "type": 0}, None),
            ({"id": THREAD, "type": 11, "parent_id": CHANNEL}, f"{CHANNEL}:{THREAD}"),
            ({"id": THREAD, "type": 12, "parent_id": CHANNEL}, f"{THREAD}:{THREAD}"),
        ],
    )
    async def test_new_starts_over_a_thread_and_explains_itself_in_a_channel(
        self,
        adapter: DiscordAdapter,
        api: _Discord,
        spawned: list[Any],
        channel: dict[str, Any],
        key: str | None,
    ):
        await adapter._on_interaction(
            {
                "type": 2,
                "id": "i4",
                "token": "itok",
                "guild_id": GUILD,
                "channel_id": channel["id"],
                "channel": channel,
                "member": {"user": {"id": USER}},
                "data": {"name": "new", "type": 1},
            },
            BOT,
        )
        [answer] = api.posted("/interactions/i4/itok/callback")
        if key is None:
            assert spawned == []
            assert answer == discord.NEW_OUTSIDE_THREAD
        else:
            [incoming] = spawned
            assert incoming.platform_chat_id == key
            assert answer == {"type": 5, "data": {"flags": 64}}

    async def test_ask_about_a_message_with_only_a_file_hands_over_the_file(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        url = "https://cdn.discordapp.com/attachments/1/2/image.png"
        await adapter._on_interaction(
            {
                "type": 2,
                "id": "i3",
                "token": "itok",
                "guild_id": GUILD,
                "channel_id": CHANNEL,
                "member": {"user": {"id": USER}},
                "data": {
                    "name": "Ask the agent",
                    "type": 3,
                    "target_id": MESSAGE,
                    "resolved": {
                        "messages": {
                            MESSAGE: {
                                "content": "",
                                "attachments": [
                                    {
                                        "filename": "image.png",
                                        "content_type": "image/webp",
                                        "size": 10,
                                        "url": url,
                                    }
                                ],
                            }
                        }
                    },
                },
            },
            BOT,
        )
        [incoming] = spawned
        assert incoming.attachments == [
            IncomingAttachment(filename="image.png", mime_type="image/png", size=10, handle=url)
        ]

    async def test_an_unknown_command_is_ignored(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        await adapter._on_interaction(
            {"type": 2, "id": "i", "token": "t", "data": {"name": "nope", "type": 1}}, BOT
        )
        assert spawned == []
        assert api.calls == []

    async def test_a_press_is_acknowledged_at_once_and_routed(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        await adapter._on_interaction(
            {
                "type": 3,
                "id": "i4",
                "token": "itok",
                "channel_id": THREAD,
                "member": {"user": {"id": USER, "username": "ada"}},
                "message": {"id": "m1", "content": "Run it?"},
                "data": {"component_type": 2, "custom_id": "aos:p:0"},
            },
            BOT,
        )
        [press] = spawned
        assert isinstance(press, IncomingPress)
        assert (press.platform_chat_id, press.message_id, press.value) == (THREAD, "m1", "aos:p:0")
        assert press.ack_id == "itok"
        assert api.posted("/interactions/i4/itok/callback") == [{"type": 6}]

    async def test_a_thumbs_down_opens_the_form(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        await adapter._on_interaction(
            {
                "type": 3,
                "id": "i5",
                "token": "itok",
                "channel_id": "dm",
                "user": {"id": USER},
                "data": {"component_type": 2, "custom_id": "aosfb:run-1:-"},
            },
            BOT,
        )
        [body] = api.posted("/interactions/i5/itok/callback")
        assert body["type"] == 9
        assert body["data"]["custom_id"] == "aosfc:run-1"
        assert len(spawned) == 1

    async def test_a_component_with_no_value_is_ignored(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        await adapter._on_interaction(
            {"type": 3, "id": "i", "token": "t", "data": {"component_type": 3, "values": []}}, BOT
        )
        assert spawned == []

    async def test_an_interaction_token_never_reaches_a_trace(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        await adapter._on_interaction(
            {"type": 3, "id": "i9", "token": "itok", "data": {"custom_id": "aos:p:0"}}, BOT
        )
        await adapter._learn_channel("tok", CHANNEL)
        assert api.traced == [
            ("/interactions/i9/itok/callback", False),
            (f"/channels/{CHANNEL}", True),
        ]

    async def test_a_submitted_form_is_kept_as_a_comment(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        form = {
            "custom_id": "aosfc:run-1",
            "components": [{"components": [{"custom_id": "comment", "value": "wrong date"}]}],
        }
        await adapter._on_interaction(
            {"type": 5, "id": "i6", "token": "itok", "user": {"id": USER}, "data": form}, BOT
        )
        await adapter._on_interaction(
            {"type": 5, "id": "i7", "token": "itok", "user": {"id": USER}, "data": {}}, BOT
        )
        assert api.posted("/interactions/i6/itok/callback") == [{"type": 5, "data": {"flags": 64}}]
        assert api.posted("/interactions/i7/itok/callback") == [
            {"type": 4, "data": {"content": "There was no comment to keep.", "flags": 64}}
        ]
        [keeping] = spawned
        kept = AsyncMock(return_value=True)
        with patch.object(discord, "process_feedback_comment", kept):
            await asyncio.wait_for(keeping, timeout=5)
        [comment] = kept.await_args.args
        assert (comment.run_id, comment.text, comment.platform_user_id) == (
            "run-1",
            "wrong date",
            USER,
        )
        [(method, path, body)] = api.calls[2:]
        assert (method, path) == ("PATCH", f"/webhooks/{APP}/itok/messages/@original")
        assert body["content"] == "Thanks - that goes to the agent's builders."

    async def test_a_comment_that_could_not_be_kept_does_not_say_thanks(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        comment = FeedbackComment(
            platform="discord", bot_id=BOT, platform_user_id=USER, run_id="run-1", text="no"
        )
        with patch.object(discord, "process_feedback_comment", AsyncMock(return_value=False)):
            await adapter._keep_comment(APP, "itok", comment)
        [(_, _, body)] = api.calls
        assert "/link" in body["content"]
        assert body["allowed_mentions"] == {"parse": []}


class _Socket:
    """A Gateway connection: a scripted hello and frames, recording what is sent."""

    def __init__(self, frames: list[dict[str, Any]], close_code: int | None) -> None:
        self.url = ""
        self.sent: list[dict[str, Any]] = []
        self.closed: list[int] = []
        self._frames = frames
        self.close_code = close_code

    async def recv(self) -> str:
        return json.dumps({"op": 10, "d": {"heartbeat_interval": 45000}})

    async def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def close(self, code: int, reason: str) -> None:
        self.closed.append(code)

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[str]:
        for frame in self._frames:
            # A real socket waits between frames, which is when work spawned by the
            # last one gets to run.
            await asyncio.sleep(0)
            yield json.dumps(frame)
        if self.close_code not in (None, 1000):
            raise ConnectionClosedError(Close(self.close_code, ""), None)


def _connect(socket: _Socket) -> Any:
    @asynccontextmanager
    async def connect(url: str, **_: Any) -> AsyncIterator[_Socket]:
        socket.url = url
        yield socket

    return connect


@pytest.fixture
def state() -> Iterator[AsyncMock]:
    with (
        patch.object(discord.connection_state, "record_up", AsyncMock()) as up,
        patch.object(discord.connection_state, "heartbeat", AsyncMock()),
    ):
        yield up


class TestGateway:
    async def test_a_session_identifies_registers_its_commands_and_reports_up(
        self, adapter: DiscordAdapter, api: _Discord, state: AsyncMock, spawned: list[Any]
    ):
        adapter._own_ids.clear()
        api.answer("GET", "/gateway/bot", httpx.Response(200, json={"url": "wss://gw.example"}))
        ready = {
            "op": 0,
            "s": 1,
            "t": "READY",
            "d": {
                "session_id": "s1",
                "resume_gateway_url": "wss://resume.example",
                "user": {"id": OWN},
                "application": {"id": APP},
            },
        }
        socket = _Socket([ready], close_code=None)
        with patch.object(discord, "connect", _connect(socket)):
            await adapter._run_stream(BOT, "tok")

        assert socket.url == "wss://gw.example/?v=10&encoding=json"
        assert socket.sent[0]["op"] == 2
        assert adapter._own_ids[BOT] == OWN
        [registering] = spawned
        await asyncio.wait_for(registering, timeout=5)
        assert [p for m, p, _ in api.calls if m == "PUT"] == [f"/applications/{APP}/commands"]
        state.assert_awaited()
        session = adapter._sessions[BOT]
        assert (session.session_id, session.resume_url, session.seq) == (
            "s1",
            "wss://resume.example",
            1,
        )

    async def test_a_dropped_session_is_resumed_where_it_stopped(
        self, adapter: DiscordAdapter, api: _Discord, state: AsyncMock
    ):
        adapter._sessions[BOT] = _Session(
            session_id="s1", resume_url="wss://resume.example/", seq=9
        )
        socket = _Socket([{"op": 0, "t": "RESUMED", "d": {}}], close_code=4000)
        with patch.object(discord, "connect", _connect(socket)):
            await adapter._run_stream(BOT, "tok")
        assert socket.sent[0] == {"op": 6, "d": {"token": "tok", "session_id": "s1", "seq": 9}}
        assert socket.url == "wss://resume.example/?v=10&encoding=json"
        assert BOT in adapter._sessions

    async def test_a_lost_session_identifies_afresh_next_time(
        self, adapter: DiscordAdapter, api: _Discord, state: AsyncMock
    ):
        adapter._sessions[BOT] = _Session(session_id="s1", resume_url="wss://r", seq=9)
        with patch.object(discord, "connect", _connect(_Socket([], close_code=4009))):
            await adapter._run_stream(BOT, "tok")
        assert BOT not in adapter._sessions

    async def test_a_refused_intent_stops_the_bot_with_what_to_switch_on(
        self, adapter: DiscordAdapter, api: _Discord, state: AsyncMock
    ):
        api.answer("GET", "/gateway/bot", httpx.Response(200, json={"url": "wss://gw"}))
        with (
            patch.object(discord, "connect", _connect(_Socket([], close_code=4014))),
            pytest.raises(ChannelNotConfigured, match="Message Content Intent"),
        ):
            await adapter._run_stream(BOT, "tok")

    async def test_a_public_bot_stops_before_connecting(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer("GET", "/gateway/bot", httpx.Response(200, json={"url": "wss://gw"}))
        api.answer("GET", "/applications/@me", httpx.Response(200, json={"bot_public": True}))
        connect = AsyncMock()
        with (
            patch.object(discord, "connect", connect),
            pytest.raises(ChannelNotConfigured, match="Public Bot"),
        ):
            await adapter._run_stream(BOT, "tok")
        connect.assert_not_called()

    async def test_a_bot_made_public_stops_when_it_is_added_to_a_server(
        self, adapter: DiscordAdapter, api: _Discord, state: AsyncMock
    ):
        """The check before connecting cannot see a switch flipped afterwards."""
        api.answer("GET", "/gateway/bot", httpx.Response(200, json={"url": "wss://gw"}))
        api.answer(
            "GET",
            "/applications/@me",
            httpx.Response(200, json={"bot_public": False}),
            httpx.Response(200, json={"bot_public": True}),
        )
        ready = {
            "op": 0,
            "s": 1,
            "t": "READY",
            "d": {"session_id": "s1", "guilds": [{"id": GUILD}]},
        }
        known = {"op": 0, "s": 2, "t": "GUILD_CREATE", "d": {"id": GUILD}}
        added = {"op": 0, "s": 3, "t": "GUILD_CREATE", "d": {"id": "g2"}}
        later = {"op": 0, "s": 4, "t": "TYPING_START", "d": {}}
        socket = _Socket([ready, known, added, *([later] * 200)], close_code=None)
        with (
            patch.object(discord, "connect", _connect(socket)),
            pytest.raises(ChannelNotConfigured, match="Public Bot"),
        ):
            await adapter._run_stream(BOT, "tok")
        assert [p for _, p, _ in api.calls].count("/applications/@me") == 2
        # A real socket stops delivering once closed; this one keeps scripted frames.
        assert socket.closed and set(socket.closed) == {1000}
        assert BOT not in adapter._sessions

    async def test_a_private_bot_added_to_a_server_stays_connected(
        self, adapter: DiscordAdapter, api: _Discord, state: AsyncMock
    ):
        api.answer("GET", "/gateway/bot", httpx.Response(200, json={"url": "wss://gw"}))
        added = {"op": 0, "s": 1, "t": "GUILD_CREATE", "d": {"id": "g2"}}
        socket = _Socket([added], close_code=None)
        with patch.object(discord, "connect", _connect(socket)):
            await adapter._run_stream(BOT, "tok")
        assert socket.closed == []
        assert adapter._sessions[BOT].guilds == {"g2"}

    async def test_a_beat_lost_to_a_closing_socket_leaves_the_close_code_to_decide(
        self, adapter: DiscordAdapter, api: _Discord, state: AsyncMock
    ):
        """A beat sent as Discord closed fails too; 4004 must still stop the bot."""

        class _Closing(_Socket):
            async def _iterate(self) -> AsyncIterator[str]:
                await asyncio.sleep(0)
                raise ConnectionClosedError(Close(4004, ""), None)
                yield ""

        async def beat(*_: Any) -> None:
            raise ConnectionClosedError(Close(4004, ""), None)

        api.answer("GET", "/gateway/bot", httpx.Response(200, json={"url": "wss://gw"}))
        with (
            patch.object(adapter, "_heartbeat", beat),
            patch.object(discord, "connect", _connect(_Closing([], close_code=4004))),
            pytest.raises(ChannelNotConfigured),
        ):
            await adapter._run_stream(BOT, "tok")

    async def test_a_rejected_token_stops_before_connecting(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer("GET", "/gateway/bot", httpx.Response(401))
        with pytest.raises(ChannelNotConfigured, match="token"):
            await adapter._run_stream(BOT, "tok")

    async def test_the_gateway_s_own_requests_are_answered(self, adapter: DiscordAdapter):
        socket = _Socket([], close_code=None)
        session = _Session(seq=3, acked=False)
        for frame in (
            {"op": 11},
            {"op": 1},
            {"op": 7},
            {"op": 9, "d": True},
            "not json",
        ):
            await adapter._on_frame(
                json.dumps(frame) if isinstance(frame, dict) else frame, socket, BOT, "tok", session
            )
        assert session.acked is True
        assert socket.sent == [{"op": 1, "d": 3}]
        assert socket.closed == [4000, 4000]
        assert session.seq == 3

        session.session_id = "s"
        await adapter._on_frame(json.dumps({"op": 9, "d": False}), socket, BOT, "tok", session)
        assert (session.session_id, session.seq) == (None, None)

    async def test_an_unacknowledged_heartbeat_closes_the_connection_to_resume(
        self, adapter: DiscordAdapter
    ):
        socket = _Socket([], close_code=None)
        session = _Session(seq=5)
        with patch.object(discord.asyncio, "sleep", AsyncMock()):
            await adapter._heartbeat(socket, 0.0, session)
        assert socket.sent == [{"op": 1, "d": 5}]
        assert socket.closed == [4000]

    async def test_a_failing_event_is_logged_not_fatal(self, adapter: DiscordAdapter):
        with patch.object(adapter, "_on_dispatch", AsyncMock(side_effect=RuntimeError("boom"))):
            await adapter._on_frame(
                json.dumps({"op": 0, "s": 4, "t": "X", "d": {}}),
                _Socket([], None),
                BOT,
                "tok",
                _Session(),
            )

    async def test_channels_are_learned_from_the_gateway_and_looked_up_once(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any], state: AsyncMock
    ):
        session = _Session(guilds={GUILD})
        await adapter._on_dispatch(
            "GUILD_CREATE",
            {
                "id": GUILD,
                "channels": [{"id": CHANNEL, "type": 0}],
                "threads": [{"id": THREAD, "type": 11, "parent_id": CHANNEL}],
            },
            BOT,
            "tok",
            session,
        )
        await adapter._on_dispatch(
            "THREAD_CREATE", {"id": "t2", "type": 11, "parent_id": CHANNEL}, BOT, "tok", session
        )
        await adapter._on_dispatch(
            "THREAD_LIST_SYNC",
            {"threads": [{"id": "t3", "type": 12, "parent_id": CHANNEL}]},
            BOT,
            "tok",
            session,
        )
        await adapter._on_dispatch("RESUMED", {}, BOT, "tok", session)
        assert all(key in adapter._channels for key in (CHANNEL, THREAD, "t2", "t3"))

        api.answer(
            "GET",
            "/channels/new",
            httpx.Response(200, json={"id": "new", "type": 11, "parent_id": CHANNEL}),
        )
        for _ in range(2):
            await adapter._on_dispatch(
                "MESSAGE_CREATE", _message(channel_id="new", id="m9"), BOT, "tok", session
            )
            await spawned.pop()
        assert [p for m, p, _ in api.calls if m == "GET"] == ["/channels/new"]
        assert [incoming.platform_chat_id for incoming in spawned] == [f"{CHANNEL}:new"] * 2

        await adapter._on_dispatch(
            "MESSAGE_CREATE", _message(author={"bot": True}), BOT, "tok", session
        )
        await spawned.pop()
        await adapter._on_dispatch("INTERACTION_CREATE", {"type": 4}, BOT, "tok", session)
        await spawned.pop()
        assert len(spawned) == 2

    async def test_the_receive_loop_never_waits_on_discord(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        session = _Session()
        await adapter._on_dispatch(
            "MESSAGE_CREATE", _message(channel_id="unknown"), BOT, "tok", session
        )
        await adapter._on_dispatch(
            "INTERACTION_CREATE",
            {"type": 3, "id": "i", "token": "t", "data": {"custom_id": "aos:p:0"}},
            BOT,
            "tok",
            session,
        )
        assert api.calls == []
        assert len(spawned) == 2
        for handler in spawned:
            handler.close()

    async def test_commands_are_registered_once_and_a_failure_is_retried(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer(
            "PUT",
            f"/applications/{APP}/commands",
            httpx.Response(500),
            httpx.Response(200, json=[]),
        )
        waits = AsyncMock()
        with patch.object(discord.asyncio, "sleep", waits):
            for _ in range(2):
                await adapter._register_commands(BOT, "tok")
        assert len([m for m, _, _ in api.calls if m == "PUT"]) == 2
        assert [call.args[0] for call in waits.await_args_list] == [0.0, 5.0, 0.0]
        adapter._app_ids.clear()
        await adapter._register_commands("other", "tok")
        assert len(api.calls) == 2

    async def test_registration_gives_up_after_its_last_attempt(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer("PUT", f"/applications/{APP}/commands", httpx.Response(503))
        unreachable = AsyncMock(side_effect=httpx.ConnectError("down"))
        with patch.object(discord.asyncio, "sleep", AsyncMock()):
            await adapter._register_commands(BOT, "tok")
            with patch.object(adapter, "_call", unreachable):
                await adapter._register_commands(BOT, "tok")
        assert len(api.calls) == 1 + len(discord._REGISTER_BACKOFF)
        assert unreachable.await_count == 1 + len(discord._REGISTER_BACKOFF)
        assert APP not in adapter._registered

    async def test_a_bot_given_another_application_s_token_registers_its_commands_there(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        await adapter._register_commands(BOT, "tok")
        adapter._app_ids[BOT] = "801"
        await adapter._register_commands(BOT, "tok")
        assert [p for m, p, _ in api.calls if m == "PUT"] == [
            f"/applications/{APP}/commands",
            "/applications/801/commands",
        ]

    async def test_polling_starts_once_and_stops(self, adapter: DiscordAdapter):
        with patch.object(adapter, "_supervise", AsyncMock()):
            await adapter.start_polling(BOT, "tok")
            first = adapter._socket_tasks[BOT]
            await adapter.start_polling(BOT, "tok")
            assert adapter._socket_tasks[BOT] is first
            adapter._sessions[BOT] = _Session(session_id="s")
            await adapter.stop_polling(BOT)
        assert BOT not in adapter._socket_tasks
        assert BOT not in adapter._sessions


class TestMembership:
    def _routes(
        self, api: _Discord, *, overwrites: list[dict[str, Any]], member: httpx.Response
    ) -> None:
        api.answer(
            "GET",
            f"/channels/{CHANNEL}",
            httpx.Response(
                200,
                json={
                    "id": CHANNEL,
                    "type": 0,
                    "guild_id": GUILD,
                    "permission_overwrites": overwrites,
                },
            ),
        )
        api.answer(
            "GET",
            f"/guilds/{GUILD}",
            httpx.Response(
                200,
                json={"owner_id": "1", "roles": [{"id": GUILD, "permissions": str(VIEW_CHANNEL)}]},
            ),
        )
        api.answer("GET", f"/guilds/{GUILD}/members/{USER}", member)

    async def test_somebody_who_can_see_the_channel_is_in_it(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        self._routes(api, overwrites=[], member=httpx.Response(200, json={"roles": []}))
        assert await adapter.is_channel_member("tok", CHANNEL, USER, api_base_url=None)

    async def test_a_private_channel_leaves_out_who_cannot_see_it(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        self._routes(
            api,
            overwrites=[{"id": GUILD, "type": 0, "deny": str(VIEW_CHANNEL), "allow": "0"}],
            member=httpx.Response(200, json={"roles": []}),
        )
        assert not await adapter.is_channel_member("tok", CHANNEL, USER, api_base_url=None)

    async def test_somebody_who_left_the_server_is_not_in_it(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        self._routes(api, overwrites=[], member=httpx.Response(404))
        assert not await adapter.is_channel_member("tok", CHANNEL, USER, api_base_url=None)

    async def test_a_thread_is_judged_by_its_parent(self, adapter: DiscordAdapter, api: _Discord):
        self._routes(api, overwrites=[], member=httpx.Response(200, json={"roles": []}))
        api.answer(
            "GET",
            f"/channels/{THREAD}",
            httpx.Response(200, json={"type": 11, "parent_id": CHANNEL}),
        )
        assert await adapter.is_channel_member("tok", THREAD, USER, api_base_url=None)

    async def test_a_private_thread_holds_only_its_members(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        self._routes(api, overwrites=[], member=httpx.Response(200, json={"roles": []}))
        api.answer(
            "GET",
            f"/channels/{THREAD}",
            httpx.Response(200, json={"type": 12, "parent_id": CHANNEL}),
        )
        api.answer("GET", f"/channels/{THREAD}/thread-members/{USER}", httpx.Response(200))
        assert await adapter.is_channel_member("tok", THREAD, USER, api_base_url=None)
        api.answer("GET", f"/channels/{THREAD}/thread-members/{USER}", httpx.Response(404))
        assert not await adapter.is_channel_member("tok", THREAD, USER, api_base_url=None)

    async def test_a_direct_message_holds_its_recipient(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer(
            "GET",
            "/channels/dm",
            httpx.Response(200, json={"type": 1, "recipients": [{"id": USER}]}),
        )
        assert await adapter.is_channel_member("tok", "dm", USER, api_base_url=None)
        assert not await adapter.is_channel_member("tok", "dm", "other", api_base_url=None)

    async def test_a_channel_the_bot_cannot_see_holds_nobody(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer("GET", "/channels/gone", httpx.Response(404))
        assert not await adapter.is_channel_member("tok", "gone", USER, api_base_url=None)


class TestTheRest:
    async def test_a_file_is_fetched_only_from_discord_s_cdn(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        assert (
            await adapter.download_attachment(
                "tok",
                IncomingAttachment(
                    "q.pdf", "application/pdf", 1, "https://cdn.discordapp.com/a/q.pdf"
                ),
            )
            == b'{"id":"1001"}'
        )
        with pytest.raises(ValueError, match="Discord attachment"):
            await adapter.download_attachment(
                "tok",
                IncomingAttachment("q.pdf", "application/pdf", 1, "http://169.254.169.254/latest"),
            )

    async def test_there_is_no_webhook(self, adapter: DiscordAdapter):
        assert await adapter.register_webhook("tok", "https://x", None) is False
        assert await adapter.delete_webhook("tok") is False
        assert adapter.verify_webhook_signature({}, "s", "{}") is False

    async def test_the_shared_client_is_closed(self, adapter: DiscordAdapter):
        await adapter.aclose()
        assert adapter._http.is_closed


def test_an_error_code_is_read_from_discord_s_body():
    assert discord._error_code(httpx.Response(400, json={"code": 160004})) == 160004
    assert discord._error_code(httpx.Response(400, text="nope")) is None
    assert discord._error_code(httpx.Response(400, json={"code": "x"})) is None


class TestWhatWasSaidBeforeTheBot:
    """The transcript and the files of a thread the bot was brought into partway."""

    def _history(self, api: _Discord, path: str) -> None:
        api.answer(
            "GET",
            path,
            httpx.Response(
                200,
                json=[
                    {
                        "id": "3",
                        "type": 0,
                        "content": "and then?",
                        "timestamp": "2026-11-01T10:02:00+00:00",
                        "author": {"id": USER, "username": "ada", "global_name": "Ada"},
                    },
                    {
                        "id": "2",
                        "type": 7,
                        "content": "",
                        "timestamp": "2026-11-01T10:01:00+00:00",
                        "author": {"id": "7", "username": "grace"},
                    },
                    {
                        "id": "1",
                        "type": 19,
                        "content": "the refund window is 30 days",
                        "timestamp": "2026-11-01T10:00:00+00:00",
                        "author": {"id": "8", "username": "grace"},
                        "attachments": [
                            {
                                "filename": "policy.pdf",
                                "size": 12,
                                "content_type": "application/pdf",
                                "url": "https://cdn.discordapp.com/attachments/1/2/policy.pdf",
                            }
                        ],
                    },
                ],
            ),
        )

    async def test_a_thread_is_read_by_its_own_id_oldest_first_without_system_messages(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        self._history(api, f"/channels/{THREAD}/messages")

        posts = await adapter.channel_history(
            "tok", CHANNEL, api_base_url=None, limit=20, thread_id=THREAD
        )

        assert [(post.author, post.text, post.post_id) for post in posts] == [
            ("grace", "the refund window is 30 days", "1"),
            ("Ada", "and then?", "3"),
        ]
        assert posts[0].posted_at is not None and posts[0].posted_at.year == 2026
        assert posts[1].author_id == USER
        assert [path for _, path, _ in api.calls] == [f"/channels/{THREAD}/messages"]

    async def test_without_a_thread_the_channel_is_read(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        self._history(api, f"/channels/{CHANNEL}/messages")

        posts = await adapter.channel_history("tok", CHANNEL, api_base_url=None, limit=500)

        assert len(posts) == 2
        assert api.calls[0][1] == f"/channels/{CHANNEL}/messages"

    async def test_files_are_those_people_posted_not_the_bots_own(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        self._history(api, f"/channels/{THREAD}/messages")

        handles = await adapter.thread_attachments(
            "tok", CHANNEL, thread_id=THREAD, api_base_url=None, limit=20
        )

        assert [item.filename for item in handles] == ["policy.pdf"]

    async def test_a_bots_upload_is_not_fed_back_to_it(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer(
            "GET",
            f"/channels/{THREAD}/messages",
            httpx.Response(
                200,
                json=[
                    {
                        "id": "9",
                        "type": 0,
                        "content": "here is the chart",
                        "author": {"id": OWN, "username": "bot", "bot": True},
                        "attachments": [
                            {
                                "filename": "chart.png",
                                "size": 5,
                                "content_type": "image/png",
                                "url": "https://cdn.discordapp.com/attachments/1/2/chart.png",
                            }
                        ],
                    }
                ],
            ),
        )

        assert not await adapter.thread_attachments(
            "tok", CHANNEL, thread_id=THREAD, api_base_url=None, limit=20
        )

    async def test_a_channel_the_bot_cannot_read_raises_for_the_router_to_report(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer("GET", f"/channels/{THREAD}/messages", httpx.Response(403, json={}))

        with pytest.raises(httpx.HTTPStatusError):
            await adapter.channel_history(
                "tok", CHANNEL, api_base_url=None, limit=5, thread_id=THREAD
            )


class TestWhatCodexAskedFor:
    """Behaviour each review round turned up, pinned."""

    def _press(self, prompt: str) -> IncomingPress:
        return IncomingPress(
            platform="discord",
            bot_id=BOT,
            platform_user_id=USER,
            platform_chat_id=CHANNEL,
            value="aos:x",
            message_id="m1",
            prompt_text=prompt,
        )

    async def test_a_long_prompt_is_cut_so_the_choice_stays_on_the_settled_message(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        await adapter.settle_prompt("tok", self._press("q" * 2000), "Approve")

        [(_, _, body)] = [call for call in api.calls if call[0] == "PATCH"]
        assert len(body["content"]) <= 2000
        assert body["content"].endswith("**Approve**")
        assert body["components"] == []

    async def test_an_attachment_download_is_kept_out_of_tracing(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        await adapter.download_attachment(
            "tok",
            IncomingAttachment(
                filename="a.txt",
                mime_type="text/plain",
                size=1,
                handle="https://cdn.discordapp.com/attachments/1/2/a.txt?ex=sig",
            ),
        )

        assert api.traced[-1] == ("/attachments/1/2/a.txt", False)

    async def test_a_new_ready_forgets_the_roles_of_the_bot_it_replaces(
        self, adapter: DiscordAdapter
    ):
        adapter._own_roles[BOT] = {"old-bot-role"}
        session = _Session()

        await adapter._on_dispatch("READY", {"session_id": "s1", "guilds": []}, BOT, "tok", session)

        assert adapter._own_roles[BOT] == set()

    async def test_stopping_a_bot_forgets_its_roles(self, adapter: DiscordAdapter):
        adapter._own_roles[BOT] = {"role"}

        await adapter.stop_polling(BOT)

        assert BOT not in adapter._own_roles

    async def test_what_a_server_sends_while_it_is_being_checked_is_not_read(
        self, adapter: DiscordAdapter, spawned: list[Any]
    ):
        session = _Session(unchecked={"g2"})

        await adapter._on_dispatch("MESSAGE_CREATE", _message(guild_id="g2"), BOT, "tok", session)
        await adapter._on_dispatch(
            "INTERACTION_CREATE", {"guild_id": "g2", "type": 2}, BOT, "tok", session
        )

        assert spawned == []

    async def test_a_check_that_fails_does_not_stop_the_connection(
        self, adapter: DiscordAdapter, api: _Discord
    ):
        api.answer("GET", "/applications/@me", httpx.Response(500, json={}))
        session = _Session(unchecked={"g2"})

        await adapter._check_public("g2", "tok", session)

        assert session.refusal is None and session.unchecked == set()

    async def test_ask_from_somebody_the_bot_turns_away_posts_nothing(
        self, adapter: DiscordAdapter, api: _Discord, spawned: list[Any]
    ):
        with patch.object(
            discord, "refusal_before_publishing", AsyncMock(return_value="Not on this bot.")
        ):
            await adapter._on_interaction(
                {
                    "type": 2,
                    "id": "i1",
                    "token": "itok",
                    "guild_id": GUILD,
                    "channel": {"id": CHANNEL, "type": 0},
                    "member": {"user": {"id": USER, "username": "ada"}},
                    "data": {
                        "name": "ask",
                        "type": 1,
                        "options": [{"value": "buy now: x.example"}],
                    },
                },
                BOT,
            )

        [body] = api.posted("/interactions/i1/itok/callback")
        assert body["data"] == {"content": "Not on this bot.", "flags": 64}
        assert spawned == []

    async def test_a_refusal_found_off_the_receive_loop_closes_a_quiet_connection(
        self, adapter: DiscordAdapter
    ):
        socket = _Socket([], close_code=None)

        with patch.object(discord.random, "random", return_value=0):
            await adapter._heartbeat(socket, 45, _Session(refusal="Public Bot"))

        assert socket.closed == [1000]
