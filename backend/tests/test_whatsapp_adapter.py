"""The WhatsApp adapter: what it sends, the typing indicator it keeps up, send health (#2076)."""

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.workspaces import Workspace
from pydantic_ai_backends import StateBackend

from app.services.channels import get_adapter, register_adapter, whatsapp
from app.services.channels.attachments import channel_file_sender
from app.services.channels.base import (
    ChannelChoice,
    IncomingAttachment,
    IncomingPress,
    OutgoingAttachment,
    OutgoingMessage,
    PromptMessage,
)
from app.services.channels.directory import BoundChannelDirectory
from app.services.channels.whatsapp import (
    FILE_NOT_SENT,
    TRANSCRIPTION_MAX_BYTES,
    WhatsAppAdapter,
    whatsapp_adapter,
)
from app.services.channels.whatsapp_format import MAX_TEXT_UNITS, to_whatsapp, utf16_units
from app.services.channels.whatsapp_graph import (
    TOKEN_REFUSED,
    MediaInfo,
    WhatsAppCredentials,
    WhatsAppGraphError,
    WhatsAppTokenRefused,
)
from app.services.channels.whatsapp_interactive import CHOOSE_BELOW
from tests.workspaces import document_workspace

pytestmark = pytest.mark.anyio

BOT_ID = str(uuid.uuid4())
CHAT = "US.13491208655302741918"
CREDS = WhatsAppCredentials(bot_id=BOT_ID, access_token="EAAG-secret", phone_number_id="104567")
TOKEN = CREDS.encode()


def _graph() -> MagicMock:
    graph = MagicMock()
    graph.send_text = AsyncMock(return_value="wamid.out")
    graph.mark_read = AsyncMock()
    graph.media_info = AsyncMock(
        return_value=MediaInfo(url="https://lookaside.fbsbx.com/x", mime_type=None, file_size=None)
    )
    graph.download_media = AsyncMock(return_value=b"bytes")
    graph.upload_media = AsyncMock(return_value="media-up")
    graph.send_media = AsyncMock(return_value="wamid.file")
    graph.send_interactive = AsyncMock(return_value="wamid.buttons")
    graph.aclose = AsyncMock()
    return graph


def _workspace_with(path: str, content: bytes) -> Workspace:
    document = StateBackend()
    document.write_bytes(f"/{path}", content)
    return document_workspace(document)


def _message(text: str = "hello", **overrides: Any) -> OutgoingMessage:
    return OutgoingMessage(platform_chat_id=CHAT, text=text, **overrides)


@pytest.fixture
def graph() -> MagicMock:
    return _graph()


@pytest.fixture
async def adapter(graph: MagicMock):
    adapter = WhatsAppAdapter(graph)
    yield adapter
    await adapter.aclose()


@pytest.fixture
def connection():
    """The shared Redis entry, as every worker sees it: one dict, three patched calls."""
    from app.services.channels.connection_state import ChannelConnection

    store: dict[str, ChannelConnection] = {}

    async def down(bot_id: str, reason: str) -> None:
        store[bot_id] = ChannelConnection(state="down", reason=reason)

    async def up(bot_id: str) -> None:
        store[bot_id] = ChannelConnection(state="up")

    async def read(bot_id: str) -> ChannelConnection | None:
        return store.get(bot_id)

    with (
        patch(
            "app.services.channels.whatsapp.connection_state.record_down",
            new=AsyncMock(side_effect=down),
        ) as d,
        patch(
            "app.services.channels.whatsapp.connection_state.record_up",
            new=AsyncMock(side_effect=up),
        ) as u,
        patch(
            "app.services.channels.whatsapp.connection_state.read", new=AsyncMock(side_effect=read)
        ),
    ):
        yield MagicMock(down=d, up=u, store=store)


class Clock:
    """The refresher's sleep, advanced by hand: no test waits on a real timer."""

    def __init__(self) -> None:
        self.ticks: asyncio.Queue[None] = asyncio.Queue()
        self.slept: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        await self.ticks.get()

    async def tick(self, times: int = 1) -> None:
        for _ in range(times):
            self.ticks.put_nowait(None)
        await settle()


async def settle() -> None:
    """Let every ready task run to its next wait."""
    for _ in range(20):
        await asyncio.sleep(0)


@pytest.fixture
def clock():
    clock = Clock()
    with patch.object(whatsapp, "_sleep", clock.sleep):
        yield clock


class TestSending:
    async def test_an_answer_is_converted_split_and_sent_in_order(self, adapter, graph):
        word = "word "
        text = "**Heading** " + word * (MAX_TEXT_UNITS // len(word) + 200)

        await adapter.send_message(TOKEN, _message(text, reply_to_message_id="wamid.in"))

        calls = graph.send_text.await_args_list
        assert len(calls) == 2
        assert calls[0].args == (CREDS,)
        assert calls[0].kwargs["body"].startswith("*Heading* word")
        assert calls[0].kwargs["recipient"] == CHAT
        assert calls[0].kwargs["reply_to"] == "wamid.in"
        assert calls[1].kwargs["reply_to"] is None
        assert all(utf16_units(c.kwargs["body"]) <= MAX_TEXT_UNITS for c in calls)

    async def test_a_leading_blank_run_does_not_cost_the_answer(self, adapter, graph):
        await adapter.send_message(TOKEN, _message(" \n" + "a" * (MAX_TEXT_UNITS + 10)))

        bodies = [c.kwargs["body"] for c in graph.send_text.await_args_list]
        assert bodies and all(body.strip() == body and body for body in bodies)
        assert "".join(bodies).count("a") == MAX_TEXT_UNITS + 10

    async def test_an_answer_with_nothing_in_it_sends_nothing(self, adapter, graph):
        await adapter.send_message(TOKEN, _message(" \n "))

        graph.send_text.assert_not_awaited()

    async def test_a_chart_with_a_short_answer_goes_as_one_captioned_image(self, adapter, graph):
        await adapter.send_message(
            TOKEN, _message("**Sales** up", image_png=b"png", image_filename="sales.png")
        )

        graph.send_text.assert_not_awaited()
        graph.upload_media.assert_awaited_once_with(
            CREDS, content=b"png", mime_type="image/png", filename="sales.png"
        )
        graph.send_media.assert_awaited_once_with(
            CREDS,
            recipient=CHAT,
            kind="image",
            media_id="media-up",
            caption="*Sales* up",
            filename="sales.png",
            reply_to=None,
        )

    async def test_a_chart_with_no_text_goes_without_a_caption(self, adapter, graph):
        await adapter.send_message(TOKEN, _message("", image_png=b"png"))

        graph.send_text.assert_not_awaited()
        assert graph.send_media.await_args.kwargs["caption"] is None

    async def test_a_long_answer_goes_first_and_the_file_after(self, adapter, graph):
        file = OutgoingAttachment("a.csv", b"x", "text/csv")

        await adapter.send_message(TOKEN, _message("a" * 2000, attachments=[file]))

        assert graph.send_text.await_count == 1
        graph.send_media.assert_awaited_once()
        sent = graph.send_media.await_args.kwargs
        assert (sent["kind"], sent["caption"], sent["filename"]) == ("document", None, "a.csv")
        order = [c[0] for c in graph.mock_calls if c[0] in {"send_text", "send_media"}]
        assert order == ["send_text", "send_media"]

    async def test_only_the_first_file_carries_the_caption(self, adapter, graph):
        files = [OutgoingAttachment("a.csv", b"x", "text/csv"), OutgoingAttachment("b.csv", b"y")]

        await adapter.send_message(TOKEN, _message("Here", image_png=b"png", attachments=files))

        captions = [c.kwargs["caption"] for c in graph.send_media.await_args_list]
        assert captions == ["Here", None, None]
        kinds = [c.kwargs["kind"] for c in graph.send_media.await_args_list]
        assert kinds == ["image", "document", "document"]

    async def test_a_large_png_goes_as_a_document(self, adapter, graph):
        big = OutgoingAttachment("big.png", b"x" * (6 * 1024 * 1024), "image/png")
        small = OutgoingAttachment("small.jpg", b"x", "image/jpeg")
        gif = OutgoingAttachment("a.gif", b"x", "image/gif")

        await adapter.send_message(TOKEN, _message("", attachments=[big, small, gif]))

        kinds = [c.kwargs["kind"] for c in graph.send_media.await_args_list]
        assert kinds == ["document", "image", "document"]

    async def test_a_failed_upload_still_sends_the_answer_with_a_note(self, adapter, graph):
        graph.upload_media.side_effect = WhatsAppGraphError(code=100)

        await adapter.send_message(
            TOKEN, _message("Here it is", attachments=[OutgoingAttachment("a.csv", b"x")])
        )

        graph.send_media.assert_not_awaited()
        [call] = graph.send_text.await_args_list
        assert call.kwargs["body"] == f"Here it is\n\n{FILE_NOT_SENT}"

    async def test_a_refused_token_during_upload_marks_the_bot_down(
        self, adapter, graph, connection
    ):
        graph.upload_media.side_effect = WhatsAppTokenRefused(code=190)

        with pytest.raises(WhatsAppTokenRefused):
            await adapter.send_message(
                TOKEN, _message("x", attachments=[OutgoingAttachment("a", b"x")])
            )

        connection.down.assert_awaited_once_with(BOT_ID, TOKEN_REFUSED)
        graph.send_text.assert_not_awaited()

    async def test_a_caption_is_counted_in_utf16_units(self, adapter, graph):
        # 600 code points, 1200 UTF-16 units: under Meta's limit by one count, over by the other.
        text = "\U0001f600" * 600
        assert len(text) <= 1024 < utf16_units(text)

        await adapter.send_message(
            TOKEN, _message(text, attachments=[OutgoingAttachment("a.csv", b"x")])
        )

        assert graph.send_text.await_count >= 1
        assert graph.send_media.await_args.kwargs["caption"] is None

    async def test_a_note_alone_follows_the_files_that_did_arrive(self, adapter, graph):
        graph.upload_media.side_effect = [WhatsAppGraphError(code=100), "ok1"]
        files = [OutgoingAttachment("a", b"x"), OutgoingAttachment("b", b"y")]

        await adapter.send_message(TOKEN, _message("", attachments=files))

        [media] = graph.send_media.await_args_list
        assert media.kwargs["caption"] is None
        [text] = graph.send_text.await_args_list
        assert text.kwargs["body"] == FILE_NOT_SENT
        order = [c[0] for c in graph.mock_calls if c[0] in {"send_text", "send_media"}]
        assert order == ["send_media", "send_text"]

    async def test_the_not_sent_note_appears_once_however_many_uploads_are_refused(
        self, adapter, graph
    ):
        graph.upload_media.side_effect = [
            WhatsAppGraphError(code=100),
            "ok",
            WhatsAppGraphError(code=100),
        ]
        files = [OutgoingAttachment(name, b"x") for name in ("a", "b", "c")]

        await adapter.send_message(TOKEN, _message("Here", attachments=files))

        [media] = graph.send_media.await_args_list
        assert media.kwargs["caption"] == f"Here\n\n{FILE_NOT_SENT}"
        graph.send_text.assert_not_awaited()

    async def test_a_refused_file_with_nothing_else_to_send_raises(self, adapter, graph):
        graph.upload_media.side_effect = WhatsAppGraphError(code=100)

        with pytest.raises(WhatsAppGraphError) as refused:
            await adapter.send_message(
                TOKEN, _message("", attachments=[OutgoingAttachment("a", b"x")])
            )

        assert refused.value.details == {"code": 100}
        graph.send_text.assert_not_awaited()

    async def test_the_file_tool_reports_a_refused_upload_as_a_failure(self, adapter, graph):
        graph.upload_media.side_effect = WhatsAppGraphError(code=100)
        sender = channel_file_sender(
            _workspace_with("report.csv", b"a,b"),
            BoundChannelDirectory(adapter=adapter, bot_token=TOKEN, channel_id=CHAT),
        )

        result = await sender("report.csv")

        graph.upload_media.assert_awaited_once()
        assert "Do not claim it was sent" in result
        assert "accepted the attachment" not in result
        graph.send_text.assert_not_awaited()

    async def test_text_files_go_up_as_plain_text_under_their_own_name(self, adapter, graph):
        files = [
            OutgoingAttachment("a.csv", b"x", "text/csv"),
            OutgoingAttachment("b.json", b"{}", "application/json"),
            OutgoingAttachment("c.pdf", b"%PDF", "application/pdf"),
        ]

        await adapter.send_message(TOKEN, _message("", attachments=files))

        uploaded = [
            (c.kwargs["mime_type"], c.kwargs["filename"])
            for c in graph.upload_media.await_args_list
        ]
        assert uploaded == [
            ("text/plain", "a.csv"),
            ("text/plain", "b.json"),
            ("application/pdf", "c.pdf"),
        ]

    async def test_the_reply_context_is_on_the_first_message_only(self, adapter, graph):
        files = [OutgoingAttachment("a.csv", b"x"), OutgoingAttachment("b.csv", b"y")]

        await adapter.send_message(
            TOKEN, _message("a" * 2000, attachments=files, reply_to_message_id="wamid.in")
        )

        text_replies = [c.kwargs["reply_to"] for c in graph.send_text.await_args_list]
        media_replies = [c.kwargs["reply_to"] for c in graph.send_media.await_args_list]
        assert text_replies[0] == "wamid.in"
        assert [*text_replies[1:], *media_replies] == [None] * (len(text_replies) - 1 + 2)

    async def test_the_reply_context_goes_on_the_first_file_when_there_is_no_text(
        self, adapter, graph
    ):
        files = [OutgoingAttachment("a.csv", b"x"), OutgoingAttachment("b.csv", b"y")]

        await adapter.send_message(
            TOKEN, _message("", attachments=files, reply_to_message_id="wamid.in")
        )

        replies = [c.kwargs["reply_to"] for c in graph.send_media.await_args_list]
        assert replies == ["wamid.in", None]


class TestReadingFiles:
    async def test_describe_fills_the_size_meta_states(self, adapter, graph):
        graph.media_info.return_value = MediaInfo(url="u", mime_type="image/jpeg", file_size=2048)
        found = IncomingAttachment("image.jpg", "image/jpeg", 0, "12345")

        [described] = await adapter.describe_attachments(TOKEN, [found])

        assert described == IncomingAttachment("image.jpg", "image/jpeg", 2048, "12345")
        graph.media_info.assert_awaited_once_with(CREDS, media_id="12345")

    async def test_describe_takes_metas_type_for_an_untyped_file(self, adapter, graph):
        graph.media_info.return_value = MediaInfo(
            url="u", mime_type="audio/ogg; codecs=opus", file_size=None
        )
        found = IncomingAttachment("audio", "application/octet-stream", 0, "12345")

        [described] = await adapter.describe_attachments(TOKEN, [found])

        assert (described.mime_type, described.size) == ("audio/ogg", 0)

    async def test_describe_keeps_the_type_the_payload_stated(self, adapter, graph):
        graph.media_info.return_value = MediaInfo(url="u", mime_type="audio/mpeg", file_size=5)
        found = IncomingAttachment("a.ogg", "audio/ogg", 0, "12345")

        [described] = await adapter.describe_attachments(TOKEN, [found])

        assert (described.mime_type, described.size) == ("audio/ogg", 5)

    async def test_describe_leaves_an_untyped_file_when_meta_names_no_type(self, adapter, graph):
        found = IncomingAttachment("audio", "application/octet-stream", 0, "12345")

        [described] = await adapter.describe_attachments(TOKEN, [found])

        assert described == found

    async def test_describe_leaves_a_named_unreadable_message_alone(self, adapter, graph):
        found = IncomingAttachment("sticker message", "application/octet-stream", 0, "wamid.X")

        assert await adapter.describe_attachments(TOKEN, [found]) == [found]
        graph.media_info.assert_not_awaited()

    async def test_a_lookup_failure_leaves_that_attachment_as_it_was(self, adapter, graph):
        graph.media_info.side_effect = [WhatsAppGraphError(code=100), MediaInfo("u", None, 7)]
        first = IncomingAttachment("a.pdf", "application/pdf", 0, "1")
        second = IncomingAttachment("b.pdf", "application/pdf", 0, "2")

        described = await adapter.describe_attachments(TOKEN, [first, second])

        assert described == [first, IncomingAttachment("b.pdf", "application/pdf", 7, "2")]

    async def test_a_voice_note_is_fetched_under_the_transcription_limit(self, adapter, graph):
        found = IncomingAttachment("audio.ogg", "audio/ogg", 10, "12345")

        data = await adapter.download_attachment(TOKEN, found)

        assert data == b"bytes"
        graph.media_info.assert_awaited_once_with(CREDS, media_id="12345")
        graph.download_media.assert_awaited_once_with(
            CREDS, url="https://lookaside.fbsbx.com/x", limit=TRANSCRIPTION_MAX_BYTES
        )

    async def test_a_document_is_fetched_under_the_upload_limit(self, adapter, graph):
        found = IncomingAttachment("a.pdf", "application/pdf", 10, "12345")

        await adapter.download_attachment(TOKEN, found)

        limit = graph.download_media.await_args.kwargs["limit"]
        assert limit == whatsapp.settings.CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024

    async def test_a_named_unreadable_message_cannot_be_downloaded(self, adapter, graph):
        graph.media_info.side_effect = WhatsAppGraphError(code=None)
        found = IncomingAttachment("sticker message", "application/octet-stream", 0, "wamid.X")

        with pytest.raises(WhatsAppGraphError):
            await adapter.download_attachment(TOKEN, found)


class TestTyping:
    async def test_begin_reply_marks_read_shows_typing_and_cannot_edit(self, adapter, graph):
        handle = await adapter.begin_reply(TOKEN, _message("…", reply_to_message_id="wamid.in"))

        assert handle is None
        graph.mark_read.assert_awaited_once_with(CREDS, message_id="wamid.in", typing=True)

    async def test_a_reply_to_nothing_shows_no_indicator(self, adapter, graph):
        assert await adapter.begin_reply(TOKEN, _message("…")) is None

        graph.mark_read.assert_not_awaited()

    async def test_typing_is_refreshed_until_the_answer_is_sent(self, adapter, graph, clock):
        await adapter.begin_reply(TOKEN, _message("…", reply_to_message_id="wamid.in"))
        await clock.tick(3)
        assert graph.mark_read.await_count == 4  # the first, then one per refresh
        assert clock.slept[0] == whatsapp.TYPING_REFRESH_SECONDS

        await adapter.send_message(TOKEN, _message("answer"))
        await clock.tick(3)

        assert graph.mark_read.await_count == 4
        assert not adapter._typing

    async def test_typing_stops_after_five_minutes_without_an_answer(self, adapter, graph, clock):
        await adapter.begin_reply(TOKEN, _message("…", reply_to_message_id="wamid.in"))
        await clock.tick(100)

        refreshes = int(whatsapp.TYPING_MAX_SECONDS // whatsapp.TYPING_REFRESH_SECONDS)
        assert graph.mark_read.await_count == 1 + refreshes
        assert not adapter._typing

    async def test_a_second_reply_in_a_chat_replaces_the_first_refresher(
        self, adapter, graph, clock
    ):
        await adapter.begin_reply(TOKEN, _message("…", reply_to_message_id="wamid.1"))
        (first,) = adapter._typing.values()
        await settle()  # let it start waiting, so the cancel lands inside it
        await adapter.begin_reply(TOKEN, _message("…", reply_to_message_id="wamid.2"))
        await settle()

        assert first.cancelled()
        assert len(adapter._typing) == 1

    async def test_a_failing_indicator_is_swallowed_and_logged_with_its_code_not_its_cause(
        self, adapter, graph, caplog
    ):
        graph.mark_read.side_effect = WhatsAppGraphError(code=131000)

        with caplog.at_level("WARNING"):
            assert await adapter.begin_reply(TOKEN, _message("…", reply_to_message_id="w")) is None
            await adapter.begin_reply("not credentials", _message("…", reply_to_message_id="w"))

        assert "EAAG-secret" not in caplog.text
        failed = [r for r in caplog.records if r.message == "whatsapp_typing_failed"]
        assert [(r.bot_id, r.code) for r in failed] == [(BOT_ID, 131000), (None, None)]

    async def test_a_refused_token_while_typing_logs_its_code(self, adapter, graph, caplog):
        graph.mark_read.side_effect = WhatsAppTokenRefused(code=190)

        with caplog.at_level("WARNING"):
            await adapter.begin_reply(TOKEN, _message("…", reply_to_message_id="w"))

        (failed,) = [r for r in caplog.records if r.message == "whatsapp_typing_failed"]
        assert failed.code == 190

    async def test_a_refresh_that_fails_ends_quietly(self, adapter, graph, clock, caplog):
        graph.mark_read.side_effect = [None, WhatsAppGraphError(code=131000)]

        with caplog.at_level("WARNING"):
            await adapter.begin_reply(TOKEN, _message("…", reply_to_message_id="wamid.in"))
            await clock.tick()

        assert graph.mark_read.await_count == 2
        assert not adapter._typing
        (failed,) = [r for r in caplog.records if r.message == "whatsapp_typing_failed"]
        assert (failed.bot_id, failed.code) == (BOT_ID, 131000)


class TestSendHealth:
    async def test_a_refused_token_marks_the_bot_down_and_a_later_send_clears_it(
        self, adapter, graph, connection
    ):
        graph.send_text.side_effect = WhatsAppTokenRefused(code=190)

        with pytest.raises(WhatsAppTokenRefused):
            await adapter.send_message(TOKEN, _message())

        connection.down.assert_awaited_once_with(BOT_ID, TOKEN_REFUSED)
        connection.up.assert_not_awaited()

        graph.send_text.side_effect = None
        await adapter.send_message(TOKEN, _message())
        await adapter.send_message(TOKEN, _message())

        connection.up.assert_awaited_once_with(BOT_ID)

    async def test_another_workers_good_send_clears_a_down_this_one_recorded(
        self, graph, connection
    ):
        """Production runs several workers: the one whose send succeeds is rarely the
        one that saw the refusal, so "down" is read from the shared entry."""
        first, second = WhatsAppAdapter(graph), WhatsAppAdapter(_graph())
        graph.send_text.side_effect = WhatsAppTokenRefused(code=190)
        try:
            with pytest.raises(WhatsAppTokenRefused):
                await first.send_message(TOKEN, _message())
            assert connection.store[BOT_ID].state == "down"

            await second.send_message(TOKEN, _message())
            assert connection.store[BOT_ID].state == "up"
        finally:
            await first.aclose()
            await second.aclose()

    async def test_a_send_that_was_never_refused_records_nothing(self, adapter, connection):
        await adapter.send_message(TOKEN, _message())

        connection.down.assert_not_awaited()
        connection.up.assert_not_awaited()

    async def test_another_failure_is_not_a_refused_token(self, adapter, graph, connection):
        graph.send_text.side_effect = WhatsAppGraphError(code=131000)

        with pytest.raises(WhatsAppGraphError):
            await adapter.send_message(TOKEN, _message())

        connection.down.assert_not_awaited()


class TestThePlatformInterface:
    async def test_there_is_nothing_to_poll_or_register(self, adapter):
        await adapter.start_polling(BOT_ID, TOKEN)
        await adapter.stop_polling(BOT_ID)

        assert await adapter.register_webhook(TOKEN, "https://x/hook", "s") is False
        assert await adapter.delete_webhook(TOKEN) is False
        assert adapter.parse_incoming({}, BOT_ID) is None

    async def test_the_signature_check_is_metas(self, adapter):
        body = b'{"a":1}'
        import hashlib
        import hmac

        good = "sha256=" + hmac.new(b"s", body, hashlib.sha256).hexdigest()

        assert adapter.verify_webhook_signature({"x-hub-signature-256": good}, "s", body.decode())
        assert not adapter.verify_webhook_signature(
            {"x-hub-signature-256": good}, "t", body.decode()
        )
        assert not adapter.verify_webhook_signature({}, "s", body.decode())
        assert not adapter.verify_webhook_signature({"x-hub-signature-256": good}, "s", None)

    async def test_closing_closes_the_graph_and_the_refreshers(self, graph):
        adapter = WhatsAppAdapter(graph)
        with patch.object(whatsapp, "TYPING_REFRESH_SECONDS", 10):
            await adapter.begin_reply(TOKEN, _message("…", reply_to_message_id="wamid.in"))
        (task,) = adapter._typing.values()

        await adapter.aclose()
        await asyncio.sleep(0)

        graph.aclose.assert_awaited_once()
        assert task.cancelled()

    async def test_the_default_graph_is_a_real_client(self):
        adapter = WhatsAppAdapter()
        try:
            assert adapter._graph is not None
        finally:
            await adapter.aclose()

    async def test_whatsapp_adapter_registers_lazily(self):
        from app.services.channels import _adapters

        saved = _adapters.pop("whatsapp", None)
        try:
            with pytest.raises(KeyError):
                get_adapter("whatsapp")
            first = whatsapp_adapter()
            assert whatsapp_adapter() is first
            assert get_adapter("whatsapp") is first
            await first.aclose()
        finally:
            _adapters.pop("whatsapp", None)
            if saved is not None:
                register_adapter(saved)


def _prompt(
    text: str = "Send it?", labels: tuple[str, ...] = ("Approve", "Reject")
) -> PromptMessage:
    return PromptMessage(
        platform_chat_id=CHAT,
        text=text,
        choices=[ChannelChoice(label=label, value=f"aos:p:{i}") for i, label in enumerate(labels)],
        bot_id=BOT_ID,
    )


def _press(**overrides: Any) -> IncomingPress:
    defaults: dict[str, Any] = {
        "platform": "whatsapp",
        "bot_id": BOT_ID,
        "platform_user_id": "org:US.1",
        "platform_chat_id": CHAT,
        "value": "aos:p:0",
        "message_id": "wamid.prompt",
        "ack_id": "wamid.tap",
        "delivery_id": "wamid.tap",
    }
    return IncomingPress(**{**defaults, **overrides})


class TestPrompts:
    @pytest.mark.security
    async def test_an_approval_is_sent_as_two_buttons(self, adapter, graph):
        await adapter.send_prompt(TOKEN, _prompt())

        graph.send_text.assert_not_awaited()
        graph.send_interactive.assert_awaited_once()
        sent = graph.send_interactive.await_args
        assert sent.args == (CREDS,)
        assert sent.kwargs["recipient"] == CHAT
        interactive = sent.kwargs["interactive"]
        assert interactive["type"] == "button"
        assert interactive["body"] == {"text": "Send it?"}
        assert [b["reply"] for b in interactive["action"]["buttons"]] == [
            {"id": "aos:p:0", "title": "Approve"},
            {"id": "aos:p:1", "title": "Reject"},
        ]

    @pytest.mark.security
    async def test_a_long_approval_text_goes_first(self, adapter, graph):
        text = "word " * 400

        await adapter.send_prompt(TOKEN, _prompt(text))

        order = [c[0] for c in graph.mock_calls if c[0] in {"send_text", "send_interactive"}]
        assert order == ["send_text", "send_interactive"]
        assert graph.send_text.await_args.kwargs["body"] == to_whatsapp(text).strip()
        assert (
            graph.send_interactive.await_args.kwargs["interactive"]["body"]["text"] == CHOOSE_BELOW
        )

    async def test_eleven_choices_fall_back_to_a_text_list(self, adapter, graph):
        labels = tuple(f"Option {n}" for n in range(11))

        await adapter.send_prompt(TOKEN, _prompt("Which?", labels))

        graph.send_interactive.assert_not_awaited()
        body = graph.send_text.await_args.kwargs["body"]
        assert body.startswith("Which?") and "- Option 10" in body

    async def test_a_refused_token_while_prompting_records_the_bot_down(
        self, adapter, graph, connection
    ):
        graph.send_interactive.side_effect = WhatsAppTokenRefused(code=190)

        with pytest.raises(WhatsAppTokenRefused):
            await adapter.send_prompt(TOKEN, _prompt())

        connection.down.assert_awaited_once_with(BOT_ID, TOKEN_REFUSED)

    async def test_a_prompt_that_sends_clears_a_down_the_bot_was_recorded_with(
        self, adapter, graph, connection
    ):
        from app.services.channels.connection_state import ChannelConnection

        connection.store[BOT_ID] = ChannelConnection(state="down", reason=TOKEN_REFUSED)

        await adapter.send_prompt(TOKEN, _prompt())

        connection.up.assert_awaited_once_with(BOT_ID)

    async def test_prompting_stops_the_typing_indicator(self, adapter, graph, clock):
        await adapter.acknowledge(TOKEN, _press())
        assert adapter._typing

        await adapter.send_prompt(TOKEN, _prompt())

        assert not adapter._typing

    async def test_a_tap_is_marked_read_with_typing(self, adapter, graph, clock):
        await adapter.acknowledge(TOKEN, _press())

        graph.mark_read.assert_awaited_once_with(CREDS, message_id="wamid.tap", typing=True)
        assert list(adapter._typing) == [(BOT_ID, CHAT)]
        await clock.tick()
        assert graph.mark_read.await_count == 2

    async def test_a_tap_with_nothing_to_mark_is_left_alone(self, adapter, graph):
        await adapter.acknowledge(TOKEN, _press(ack_id=None))

        graph.mark_read.assert_not_awaited()
        assert not adapter._typing

    async def test_a_failed_acknowledgement_is_never_fatal(self, adapter, graph):
        graph.mark_read.side_effect = WhatsAppGraphError(code=131000)

        await adapter.acknowledge(TOKEN, _press())

        assert not adapter._typing

    async def test_settling_quotes_the_prompt(self, adapter, graph):
        await adapter.settle_prompt(TOKEN, _press(), "Approved.")

        graph.send_text.assert_awaited_once_with(
            CREDS, recipient=CHAT, body="Approved.", reply_to="wamid.prompt"
        )

    @pytest.mark.parametrize(
        "failure",
        [
            WhatsAppGraphError(code=131000),
            WhatsAppTokenRefused(code=190),
            WhatsAppWindowClosed(),
            WhatsAppWindowUnavailable(),
            TimeoutError("EAAG-secret read timeout for US.13491208655302741918"),
        ],
    )
    async def test_a_settling_that_fails_is_never_fatal_and_logs_only_the_bot_and_the_type(
        self, adapter, failure, caplog
    ):
        """The quote only decorates the answer that follows; losing it must not lose the answer."""
        with (
            patch.object(adapter, "send_message", AsyncMock(side_effect=failure)),
            caplog.at_level(logging.WARNING),
        ):
            await adapter.settle_prompt(TOKEN, _press(), "Approved.")

        [record] = [r for r in caplog.records if r.message == "whatsapp_settle_failed"]
        assert record.bot_id == BOT_ID
        assert record.error == type(failure).__name__
        assert "EAAG-secret" not in caplog.text and CHAT not in caplog.text

    async def test_a_settling_with_an_unreadable_token_is_never_fatal_either(self, adapter, caplog):
        with caplog.at_level(logging.WARNING):
            await adapter.settle_prompt("not-a-token", _press(), "Approved.")

        [record] = [r for r in caplog.records if r.message == "whatsapp_settle_failed"]
        assert record.bot_id is None

    async def test_settling_without_the_prompts_id_quotes_nothing(self, adapter, graph):
        await adapter.settle_prompt(TOKEN, _press(message_id=None), "Rejected.")

        assert graph.send_text.await_args.kwargs["reply_to"] is None

    async def test_only_the_same_chat_matches(self, adapter):
        assert adapter.press_matches_chat(_press(), CHAT) is True
        assert adapter.press_matches_chat(_press(), "US.other") is False

    async def test_buttons_do_not_outlive_a_press(self, adapter):
        assert adapter.buttons_outlive_a_press is False
