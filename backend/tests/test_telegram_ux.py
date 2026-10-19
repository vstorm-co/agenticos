"""Telegram that feels native: formatting, topics, typing and the command menu (#2068)."""

from __future__ import annotations

import contextlib
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest

from app.services.channels.base import CHANNEL_COMMANDS, OutgoingAttachment, OutgoingMessage
from app.services.channels.router import ChannelMessageRouter
from app.services.channels.telegram import TelegramAdapter
from app.services.channels.telegram_format import to_telegram_html

pytestmark = pytest.mark.anyio


class TestFormatting:
    def test_prose_markdown_becomes_the_tags_telegram_knows(self):
        assert to_telegram_html(
            "# Refunds\n**30 days**, *usually*, see [policy](https://x.io/a?b=1&c=2)"
        ) == (
            '<b>Refunds</b>\n<b>30 days</b>, <i>usually</i>, see <a href="https://x.io/a?b=1&amp;c=2">policy</a>'
        )

    def test_code_is_kept_verbatim_and_escaped(self):
        markdown = "Run `a < b` then:\n```python\nif x **y**:\n    pass\n```\ndone"

        assert to_telegram_html(markdown) == (
            "Run <code>a &lt; b</code> then:\n<pre>if x **y**:\n    pass</pre>\ndone"
        )

    def test_a_snake_case_name_and_a_lone_star_are_left_alone(self):
        assert to_telegram_html("set max_retry_count * 2 & go") == (
            "set max_retry_count * 2 &amp; go"
        )

    def test_a_quote_in_a_url_cannot_end_the_attribute(self):
        assert "&quot;" in to_telegram_html('[x](https://x.io/"onmouseover)')


def _telegram(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    bot = MagicMock()
    for method in (
        "send_message",
        "send_chat_action",
        "edit_message_text",
        "send_photo",
        "send_document",
        "set_my_commands",
        "set_webhook",
    ):
        setattr(bot, method, AsyncMock(return_value=MagicMock(message_id=5)))

    @contextlib.asynccontextmanager
    async def fake_bot(token: str, **_: Any):
        yield bot

    monkeypatch.setattr(TelegramAdapter, "_bot", staticmethod(fake_bot))
    return bot


class TestTopicsAndTyping:
    def test_a_forum_topic_is_its_own_conversation(self):
        incoming = TelegramAdapter().parse_incoming(
            {
                "message": {
                    "message_id": 3,
                    "from": {"id": 9},
                    "chat": {"id": -100, "type": "supergroup"},
                    "is_topic_message": True,
                    "message_thread_id": 77,
                    "text": "hi",
                }
            },
            "b",
        )

        assert incoming is not None and incoming.platform_chat_id == "-100:77"

    async def test_a_reply_in_a_topic_stays_in_it_and_says_it_is_typing(self, monkeypatch):
        bot = _telegram(monkeypatch)

        handle = await TelegramAdapter().begin_reply(
            "t", OutgoingMessage(platform_chat_id="-100:77", text="…")
        )
        await TelegramAdapter().update_reply(
            "t", OutgoingMessage(platform_chat_id="-100:77", text="Hi"), handle or ""
        )

        assert handle == "5"
        assert bot.send_chat_action.await_args.kwargs == {
            "action": "typing",
            "chat_id": "-100",
            "message_thread_id": 77,
        }
        assert bot.send_message.await_args.kwargs["message_thread_id"] == 77
        assert bot.edit_message_text.await_args.kwargs["chat_id"] == "-100"

    async def test_a_typing_indicator_that_fails_does_not_cost_the_reply(self, monkeypatch):
        bot = _telegram(monkeypatch)
        bot.send_chat_action.side_effect = RuntimeError("flood")

        assert (
            await TelegramAdapter().begin_reply(
                "t", OutgoingMessage(platform_chat_id="42", text="…", reply_to_message_id="3")
            )
            == "5"
        )

    async def test_an_answer_is_sent_as_html_and_as_plain_text_if_refused(self, monkeypatch):
        bot = _telegram(monkeypatch)

        await TelegramAdapter().send_message(
            "t", OutgoingMessage(platform_chat_id="42", text="**done**")
        )
        assert bot.send_message.await_args.kwargs["text"] == "<b>done</b>"
        assert bot.send_message.await_args.kwargs["parse_mode"] == "HTML"
        assert "message_thread_id" not in bot.send_message.await_args.kwargs

        bot.send_message.side_effect = [TelegramBadRequest(MagicMock(), "bad"), MagicMock()]
        await TelegramAdapter().send_message(
            "t", OutgoingMessage(platform_chat_id="42", text="**done**")
        )
        assert bot.send_message.await_args.kwargs == {
            "text": "**done**",
            "parse_mode": None,
            "reply_to_message_id": None,
            "chat_id": "42",
        }

    async def test_a_chart_and_files_go_to_the_topic_too(self, monkeypatch):
        bot = _telegram(monkeypatch)

        await TelegramAdapter().send_message(
            "t", OutgoingMessage(platform_chat_id="-100:7", text="chart", image_png=b"png")
        )
        await TelegramAdapter().send_message(
            "t",
            OutgoingMessage(
                platform_chat_id="-100:7",
                text="x" * 1100,
                attachments=[
                    OutgoingAttachment(filename="a.csv", content=b"a", mime_type="text/csv")
                ],
            ),
        )

        assert bot.send_photo.await_args.kwargs["message_thread_id"] == 7
        assert bot.send_document.await_args.kwargs["message_thread_id"] == 7
        assert bot.send_message.await_args.kwargs["parse_mode"] is None


class TestTheCommandMenu:
    async def test_the_menu_lists_every_command_the_bot_answers(self, monkeypatch):
        bot = _telegram(monkeypatch)

        assert await TelegramAdapter().register_webhook("t", "https://x", "s") is True

        offered = bot.set_my_commands.await_args.args[0]
        assert [command.command for command in offered] == [name for name, _ in CHANNEL_COMMANDS]

    async def test_a_menu_that_cannot_be_set_does_not_stop_the_bot(self):
        bot = MagicMock(set_my_commands=AsyncMock(side_effect=RuntimeError("down")))

        await TelegramAdapter._offer_commands(bot)


def _router_with(agent: Any, binding: Any = MagicMock(agent_id=uuid.uuid4())) -> Any:
    return (
        patch(
            "app.services.channels.router.agent_exposure_repo.bound_to_bot",
            new=AsyncMock(return_value=binding),
        ),
        patch("app.services.channels.router.agent_repo.get", new=AsyncMock(return_value=agent)),
    )


class TestAgentsCommand:
    async def _ask(
        self, command: str, agent: Any, binding: Any = MagicMock(agent_id=uuid.uuid4())
    ) -> str | None:
        exposure, get = _router_with(agent, binding)
        with exposure, get:
            return await ChannelMessageRouter()._handle_command(
                command,
                MagicMock(platform="telegram", chat_type="private"),
                MagicMock(id=uuid.uuid4(), organization_id=uuid.uuid4()),
                MagicMock(),
                MagicMock(user_id=None),
                False,
            )

    async def test_it_says_which_agent_answers_and_what_it_does(self):
        agent = MagicMock(description="Answers refund questions.")
        agent.name = "Refunds"

        answer = await self._ask("/agents", agent)

        assert answer is not None and answer.startswith("I am Refunds: Answers refund questions.")

    async def test_an_agent_with_no_description_is_still_named(self):
        agent = MagicMock(description=None)
        agent.name = "Refunds"

        assert (await self._ask("/agents", agent) or "").startswith("I am Refunds.")

    async def test_a_bot_nobody_bound_says_who_can_fix_it(self):
        assert "administrator" in (await self._ask("/agents", None, binding=None) or "")

    async def test_help_lists_every_command(self):
        answer = await self._ask("/help", None)

        assert answer is not None
        assert all(f"/{name}" in answer for name, _ in CHANNEL_COMMANDS)
