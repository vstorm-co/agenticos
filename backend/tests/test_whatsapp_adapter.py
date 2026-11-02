"""The WhatsApp adapter: what it sends, the typing indicator it keeps up, send health (#2076)."""

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.channels import get_adapter, register_adapter, whatsapp
from app.services.channels.base import IncomingAttachment, OutgoingAttachment, OutgoingMessage
from app.services.channels.whatsapp import (
    FILES_NOT_YET,
    WhatsAppAdapter,
    whatsapp_adapter,
)
from app.services.channels.whatsapp_format import MAX_TEXT_UNITS, utf16_units
from app.services.channels.whatsapp_graph import (
    TOKEN_REFUSED,
    WhatsAppCredentials,
    WhatsAppGraphError,
    WhatsAppTokenRefused,
)

pytestmark = pytest.mark.anyio

BOT_ID = str(uuid.uuid4())
CHAT = "US.13491208655302741918"
CREDS = WhatsAppCredentials(bot_id=BOT_ID, access_token="EAAG-secret", phone_number_id="104567")
TOKEN = CREDS.encode()


def _graph() -> MagicMock:
    graph = MagicMock()
    graph.send_text = AsyncMock(return_value="wamid.out")
    graph.mark_read = AsyncMock()
    graph.aclose = AsyncMock()
    return graph


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

    async def test_files_are_announced_not_silently_dropped(self, adapter, graph):
        picture = _message("Here it is", image_png=b"png")
        file = _message("And a file", attachments=[OutgoingAttachment("a.csv", b"x", "text/csv")])
        bare = _message("", image_png=b"png")

        for msg in (picture, file, bare):
            await adapter.send_message(TOKEN, msg)

        bodies = [c.kwargs["body"] for c in graph.send_text.await_args_list]
        assert bodies[0] == f"Here it is\n\n{FILES_NOT_YET}"
        assert bodies[1] == f"And a file\n\n{FILES_NOT_YET}"
        assert bodies[2] == FILES_NOT_YET

    async def test_downloads_are_refused_until_slice_2(self, adapter):
        attachment = IncomingAttachment("image.jpg", "image/jpeg", 0, "media-1")

        with pytest.raises(NotImplementedError):
            await adapter.download_attachment(TOKEN, attachment)


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
