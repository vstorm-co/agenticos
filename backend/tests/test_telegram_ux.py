"""Telegram that feels native: formatting, topics, typing and the command menu (#2068)."""

import contextlib
import html
import re
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter

from app.agents.capabilities.channel_tools import ChannelDirectoryUnsupported
from app.services.channels.base import CHANNEL_COMMANDS, OutgoingAttachment, OutgoingMessage
from app.services.channels.exceptions import PartlyDelivered
from app.services.channels.router import ChannelMessageRouter
from app.services.channels.telegram import TelegramAdapter
from app.services.channels.telegram_format import (
    TELEGRAM_TEXT_LIMIT,
    telegram_pieces,
    to_telegram_html,
)

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

    def test_list_markers_become_bullets(self):
        assert to_telegram_html("Steps:\n- **one**\n* two\n  + nested") == (
            "Steps:\n• <b>one</b>\n• two\n  • nested"
        )

    def test_a_task_list_shows_its_boxes(self):
        assert to_telegram_html("- [ ] Buy milk\n- [x] Send email\n  * [X] nested") == (
            "☐ Buy milk\n☒ Send email\n  ☒ nested"
        )

    def test_a_dash_that_is_not_a_list_marker_stays(self):
        markdown = "a - b, -5, `- x`\n---\n```\n- in code\n```"

        assert to_telegram_html(markdown) == (
            "a - b, -5, <code>- x</code>\n---\n<pre>- in code</pre>"
        )

    def test_a_quote_in_a_url_cannot_end_the_attribute(self):
        assert "&quot;" in to_telegram_html('[x](https://x.io/"onmouseover)')


def _words(text: str) -> str:
    return "".join(text.split())


def _shown(sent_html: str) -> int:
    """A sent message's length as Telegram counts it: text after parsing, UTF-16 units."""
    shown = html.unescape(re.sub(r"<[^>]+>", "", sent_html))
    return len(shown.encode("utf-16-le")) // 2


def _visible(piece: str) -> int:
    """What Telegram counts: the converted text without its tags, in UTF-16 units."""
    return _shown(to_telegram_html(piece))


class TestSplittingALongAnswer:
    """Telegram refuses a message over 4096 characters, counted after the HTML conversion."""

    def test_a_short_answer_is_one_piece(self):
        assert telegram_pieces("**Done**") == ["**Done**"]

    def test_each_piece_fits_once_converted_and_nothing_is_lost(self):
        markdown = "\n".join(f"**Item {i}** costs < 5 & ships today" for i in range(400))

        pieces = telegram_pieces(markdown)

        assert len(pieces) > 1
        assert all(_visible(piece) <= TELEGRAM_TEXT_LIMIT for piece in pieces)
        assert all(len(piece) <= TELEGRAM_TEXT_LIMIT for piece in pieces)
        assert _words("".join(pieces)) == _words(markdown)

    def test_a_cut_inside_a_code_fence_closes_and_reopens_it(self):
        code = "\n".join(f"print({i})  # line {i}" for i in range(600))
        markdown = f"First:\n```sh\nls\n```\nThen:\n```python\n{code}\n```\nDone."

        pieces = telegram_pieces(markdown)

        assert len(pieces) > 1
        for piece in pieces:
            rendered = to_telegram_html(piece)
            assert _visible(piece) <= TELEGRAM_TEXT_LIMIT
            assert rendered.count("<pre>") == rendered.count("</pre>") >= 1
            assert "```" not in rendered
        assert all(piece.lstrip().startswith("```python") for piece in pieces[1:])

    def test_a_cut_in_a_fences_opening_line_moves_before_the_fence(self):
        markdown = "intro " * 600 + "```text " + "w " * 400 + "\ncode\n```"

        first, second = telegram_pieces(markdown)

        assert "```" not in first
        assert second.startswith("```text ")

    def test_whitespace_after_the_last_cut_is_not_a_piece(self):
        assert telegram_pieces("") == []
        assert telegram_pieces("x" * 4096 + "\n" + " " * 10) == ["x" * 4096]

    def test_markup_does_not_count_against_the_limit(self):
        """Telegram counts the text after parsing, so `&amp;` is one character."""
        pieces = telegram_pieces("&" * 10_000)

        assert [len(piece) for piece in pieces] == [4096, 4096, 1808]

    def test_a_character_outside_the_basic_plane_counts_twice(self):
        """Telegram measures text in UTF-16 units; an emoji is two of them."""
        pieces = telegram_pieces("😀" * 3000)

        assert [len(piece) for piece in pieces] == [2048, 952]

    def test_a_fence_opening_line_too_long_to_reopen_is_cut_as_text(self):
        markdown = "```pythonlongname\nab\ncd\n```"

        pieces = telegram_pieces(markdown, limit=20)

        assert all(len(piece) <= 20 for piece in pieces)
        assert not any(piece.endswith("nam\n```") for piece in pieces)
        assert _words("".join(pieces)) == _words(markdown)

    def test_a_word_longer_than_a_message_is_cut_where_it_must_be(self):
        pieces = telegram_pieces("x" * 10_000)

        assert [len(piece) for piece in pieces] == [4096, 4096, 1808]


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
        assert bot.send_message.await_args.kwargs["message_thread_id"] == 7


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


def test_bot_messages_do_not_start_a_new_channel_observation():
    assert (
        TelegramAdapter().parse_incoming(
            {
                "message": {
                    "message_id": 3,
                    "from": {"id": 9, "is_bot": True},
                    "chat": {"id": -100, "type": "supergroup"},
                    "text": "Bot reply",
                }
            },
            "bot",
        )
        is None
    )


class TestAnEditThatChangesNothing:
    """Telegram answers 400 "message is not modified" to an edit with identical text.

    That is success: the message already says what was asked. Raising it made
    the router re-post an answer already on screen.
    """

    async def test_an_unmodified_message_is_not_an_error(self, monkeypatch):
        bot = _telegram(monkeypatch)
        bot.edit_message_text.side_effect = TelegramBadRequest(
            MagicMock(), "Bad Request: message is not modified: specified new message content"
        )

        await TelegramAdapter().update_reply(
            "t", OutgoingMessage(platform_chat_id="42", text="Hi"), "5"
        )

    async def test_any_other_refused_edit_still_raises(self, monkeypatch):
        bot = _telegram(monkeypatch)
        bot.edit_message_text.side_effect = TelegramBadRequest(
            MagicMock(), "Bad Request: message to edit not found"
        )

        with pytest.raises(TelegramBadRequest):
            await TelegramAdapter().update_reply(
                "t", OutgoingMessage(platform_chat_id="42", text="Hi"), "5"
            )


class TestTheFinalEditIsFormatted:
    """The last edit carries the whole answer, so it is sent as HTML like a fresh post."""

    async def test_the_final_edit_is_sent_as_html(self, monkeypatch):
        bot = _telegram(monkeypatch)

        await TelegramAdapter().update_reply(
            "t", OutgoingMessage(platform_chat_id="42", text="**Done**", final=True), "5"
        )

        bot.edit_message_text.assert_awaited_once()
        sent = bot.edit_message_text.await_args.kwargs
        assert sent["text"] == "<b>Done</b>"
        assert sent["parse_mode"] == "HTML"

    async def test_html_telegram_refuses_falls_back_to_plain_text(self, monkeypatch):
        bot = _telegram(monkeypatch)
        bot.edit_message_text.side_effect = [
            TelegramBadRequest(MagicMock(), "Bad Request: can't parse entities"),
            MagicMock(),
        ]

        await TelegramAdapter().update_reply(
            "t", OutgoingMessage(platform_chat_id="42", text="**Done**", final=True), "5"
        )

        plain = bot.edit_message_text.await_args_list[-1].kwargs
        assert plain["text"] == "**Done**"
        assert plain["parse_mode"] is None

    async def test_an_unmodified_final_edit_is_not_retried_as_plain_text(self, monkeypatch):
        bot = _telegram(monkeypatch)
        bot.edit_message_text.side_effect = TelegramBadRequest(
            MagicMock(), "Bad Request: message is not modified: specified new message content"
        )

        await TelegramAdapter().update_reply(
            "t", OutgoingMessage(platform_chat_id="42", text="**Done**", final=True), "5"
        )

        bot.edit_message_text.assert_awaited_once()

    async def test_an_edit_mid_stream_stays_plain(self, monkeypatch):
        """Half-written Markdown is normal mid-stream, and Telegram rejects an unclosed `**`."""
        bot = _telegram(monkeypatch)

        await TelegramAdapter().update_reply(
            "t", OutgoingMessage(platform_chat_id="42", text="**Do"), "5"
        )

        sent = bot.edit_message_text.await_args.kwargs
        assert sent["text"] == "**Do"
        assert sent["parse_mode"] is None


class TestALongAnswerArrivesInPieces:
    LONG = "\n".join(f"**Point {i}**: the detail that matters & why" for i in range(300))

    async def test_empty_text_is_still_sent_for_telegram_to_refuse(self, monkeypatch):
        bot = _telegram(monkeypatch)

        await TelegramAdapter().send_message("t", OutgoingMessage(platform_chat_id="42", text=""))

        assert bot.send_message.await_args.kwargs["text"] == ""

    async def test_a_long_answer_is_sent_as_several_messages_that_fit(self, monkeypatch):
        bot = _telegram(monkeypatch)

        await TelegramAdapter().send_message(
            "t", OutgoingMessage(platform_chat_id="42", text=self.LONG, reply_to_message_id="9")
        )

        sent = [call.kwargs for call in bot.send_message.await_args_list]
        assert len(sent) > 1
        assert all(_shown(each["text"]) <= TELEGRAM_TEXT_LIMIT for each in sent)
        assert all(each["parse_mode"] == "HTML" for each in sent)
        assert [each["reply_to_message_id"] for each in sent] == [9] + [None] * (len(sent) - 1)

    async def test_a_piece_telegram_refuses_as_html_is_sent_plain_alone(self, monkeypatch):
        bot = _telegram(monkeypatch)
        refused = TelegramBadRequest(MagicMock(), "Bad Request: can't parse entities")
        calls = iter(range(100))

        def second_refused(**_: Any) -> MagicMock:
            if next(calls) == 1:
                raise refused
            return MagicMock()

        bot.send_message.side_effect = second_refused
        pieces = telegram_pieces(self.LONG)

        await TelegramAdapter().send_message(
            "t", OutgoingMessage(platform_chat_id="42", text=self.LONG)
        )

        sent = [call.kwargs for call in bot.send_message.await_args_list]
        modes = [each["parse_mode"] for each in sent]
        assert modes == ["HTML", "HTML", None] + ["HTML"] * (len(pieces) - 2)
        assert sent[2]["text"] == pieces[1]

    async def test_the_final_edit_holds_the_first_piece_and_the_rest_follow(self, monkeypatch):
        bot = _telegram(monkeypatch)

        await TelegramAdapter().update_reply(
            "t",
            OutgoingMessage(platform_chat_id="42", text=self.LONG, final=True),
            "5",
        )

        pieces = telegram_pieces(self.LONG)
        assert bot.edit_message_text.await_args.kwargs["text"] == to_telegram_html(pieces[0])
        followed = [call.kwargs for call in bot.send_message.await_args_list]
        assert [each["text"] for each in followed] == [to_telegram_html(p) for p in pieces[1:]]
        assert all(each["reply_to_message_id"] is None for each in followed)

    async def test_a_rate_limited_piece_waits_and_is_sent_again(self, monkeypatch):
        bot = _telegram(monkeypatch)
        slept = AsyncMock()
        monkeypatch.setattr("app.services.channels.telegram.asyncio.sleep", slept)
        limited = TelegramRetryAfter(MagicMock(), "Too Many Requests", retry_after=3)
        calls = iter(range(100))

        def second_limited(**_: Any) -> MagicMock:
            if next(calls) == 1:
                raise limited
            return MagicMock(message_id=5)

        bot.send_message.side_effect = second_limited

        await TelegramAdapter().send_message(
            "t", OutgoingMessage(platform_chat_id="42", text=self.LONG)
        )

        slept.assert_awaited_once_with(3)
        assert bot.send_message.await_count == len(telegram_pieces(self.LONG)) + 1

    async def test_a_long_rate_limit_wait_is_capped(self, monkeypatch):
        bot = _telegram(monkeypatch)
        slept = AsyncMock()
        monkeypatch.setattr("app.services.channels.telegram.asyncio.sleep", slept)
        bot.send_message.side_effect = [
            TelegramRetryAfter(MagicMock(), "Too Many Requests", retry_after=600),
            MagicMock(message_id=5),
        ]

        await TelegramAdapter().send_message("t", OutgoingMessage(platform_chat_id="42", text="hi"))

        slept.assert_awaited_once_with(30)

    async def test_a_piece_failing_after_the_first_is_reported_as_partly_delivered(
        self, monkeypatch
    ):
        """Retrying the whole send would post the pieces already in the chat again."""
        bot = _telegram(monkeypatch)
        bot.send_message.side_effect = [
            MagicMock(message_id=5),
            TelegramNetworkError(MagicMock(), "down"),
        ]

        with pytest.raises(PartlyDelivered) as raised:
            await TelegramAdapter().send_message(
                "t", OutgoingMessage(platform_chat_id="42", text=self.LONG)
            )

        assert raised.value.details["delivered"] == 1
        assert raised.value.details["pieces"] == len(telegram_pieces(self.LONG))

    async def test_the_first_piece_failing_is_an_ordinary_failure(self, monkeypatch):
        bot = _telegram(monkeypatch)
        bot.send_message.side_effect = TelegramNetworkError(MagicMock(), "down")

        with pytest.raises(TelegramNetworkError):
            await TelegramAdapter().send_message(
                "t", OutgoingMessage(platform_chat_id="42", text=self.LONG)
            )

    async def test_a_continuation_failing_after_the_final_edit_is_partly_delivered(
        self, monkeypatch
    ):
        bot = _telegram(monkeypatch)
        bot.send_message.side_effect = TelegramNetworkError(MagicMock(), "down")

        with pytest.raises(PartlyDelivered) as raised:
            await TelegramAdapter().update_reply(
                "t", OutgoingMessage(platform_chat_id="42", text=self.LONG, final=True), "5"
            )

        assert raised.value.details["delivered"] == 1

    async def test_the_final_edit_names_the_message_that_ends_the_answer(self, monkeypatch):
        bot = _telegram(monkeypatch)
        bot.send_message.return_value = MagicMock(message_id=77)

        last = await TelegramAdapter().update_reply(
            "t", OutgoingMessage(platform_chat_id="42", text=self.LONG, final=True), "5"
        )
        alone = await TelegramAdapter().update_reply(
            "t", OutgoingMessage(platform_chat_id="42", text="short", final=True), "5"
        )

        assert last == "77"
        assert alone is None

    async def test_a_file_failing_after_the_text_is_partly_delivered(self, monkeypatch):
        bot = _telegram(monkeypatch)
        bot.send_document.side_effect = TelegramNetworkError(MagicMock(), "down")
        files = [OutgoingAttachment(filename="r.pdf", content=b"%PDF")]

        with pytest.raises(PartlyDelivered) as raised:
            await TelegramAdapter().send_message(
                "t", OutgoingMessage(platform_chat_id="42", text=self.LONG, attachments=files)
            )

        pieces = len(telegram_pieces(self.LONG))
        assert raised.value.details["delivered"] == pieces
        assert raised.value.details["pieces"] == pieces + 1

    async def test_a_second_file_failing_after_a_captioned_one_is_partly_delivered(
        self, monkeypatch
    ):
        bot = _telegram(monkeypatch)
        bot.send_document.side_effect = [MagicMock(), TelegramNetworkError(MagicMock(), "down")]
        files = [
            OutgoingAttachment(filename="a.pdf", content=b"%PDF"),
            OutgoingAttachment(filename="b.pdf", content=b"%PDF"),
        ]

        with pytest.raises(PartlyDelivered) as raised:
            await TelegramAdapter().send_message(
                "t", OutgoingMessage(platform_chat_id="42", text="see", attachments=files)
            )

        assert raised.value.details["delivered"] == 1

    async def test_the_first_file_failing_with_nothing_sent_is_an_ordinary_failure(
        self, monkeypatch
    ):
        bot = _telegram(monkeypatch)
        bot.send_document.side_effect = TelegramNetworkError(MagicMock(), "down")

        with pytest.raises(TelegramNetworkError):
            await TelegramAdapter().send_message(
                "t",
                OutgoingMessage(
                    platform_chat_id="42",
                    text="see",
                    attachments=[OutgoingAttachment(filename="a.pdf", content=b"%PDF")],
                ),
            )

    async def test_an_edit_mid_stream_shows_what_fits(self, monkeypatch):
        bot = _telegram(monkeypatch)

        await TelegramAdapter().update_reply(
            "t", OutgoingMessage(platform_chat_id="42", text=self.LONG), "5"
        )

        assert bot.edit_message_text.await_args.kwargs["text"] == self.LONG[:TELEGRAM_TEXT_LIMIT]
        bot.send_message.assert_not_awaited()

    async def test_files_still_follow_a_long_answer(self, monkeypatch):
        bot = _telegram(monkeypatch)
        order: list[str] = []
        bot.send_message.side_effect = lambda **_: order.append("text") or MagicMock()
        bot.send_document.side_effect = lambda **_: order.append("file") or MagicMock()

        await TelegramAdapter().send_message(
            "t",
            OutgoingMessage(
                platform_chat_id="42",
                text=self.LONG,
                attachments=[
                    OutgoingAttachment(
                        filename="r.pdf", content=b"%PDF", mime_type="application/pdf"
                    )
                ],
            ),
        )

        assert order[-1] == "file"
        assert order.count("text") > 1
        assert all(
            _shown(call.kwargs["text"]) <= TELEGRAM_TEXT_LIMIT
            for call in bot.send_message.await_args_list
        )


class TestPromptsAndCaptionsAreFormatted:
    """Approvals, questions and captions carry Markdown too; Telegram shows it raw as plain text."""

    async def test_a_prompt_is_sent_as_html_with_its_buttons(self, monkeypatch):
        from app.services.channels.base import ChannelChoice, PromptMessage

        bot = _telegram(monkeypatch)
        prompt = PromptMessage(
            platform_chat_id="42",
            text="I need your approval to *create routine in Agenticos*: “Joke”",
            choices=[ChannelChoice(label="Approve", value="a:1")],
        )

        await TelegramAdapter().send_prompt("t", prompt)

        sent = bot.send_message.await_args.kwargs
        assert sent["text"] == "I need your approval to <i>create routine in Agenticos</i>: “Joke”"
        assert sent["parse_mode"] == "HTML"
        assert sent["reply_markup"].inline_keyboard[0][0].callback_data == "a:1"

    async def test_a_prompt_telegram_refuses_as_html_is_sent_plain(self, monkeypatch):
        from app.services.channels.base import ChannelChoice, PromptMessage

        bot = _telegram(monkeypatch)
        bot.send_message.side_effect = [
            TelegramBadRequest(MagicMock(), "Bad Request: can't parse entities"),
            MagicMock(message_id=5),
        ]
        prompt = PromptMessage(
            platform_chat_id="42",
            text="Approve *this*?",
            choices=[ChannelChoice(label="Approve", value="a:1")],
        )

        await TelegramAdapter().send_prompt("t", prompt)

        plain = bot.send_message.await_args.kwargs
        assert plain["text"] == "Approve *this*?"
        assert plain["parse_mode"] is None
        assert plain["reply_markup"].inline_keyboard[0][0].callback_data == "a:1"

    async def test_a_charts_caption_is_sent_as_html(self, monkeypatch):
        bot = _telegram(monkeypatch)

        await TelegramAdapter().send_message(
            "t", OutgoingMessage(platform_chat_id="42", text="**Sales** up", image_png=b"png")
        )

        sent = bot.send_photo.await_args.kwargs
        assert sent["caption"] == "<b>Sales</b> up"
        assert sent["parse_mode"] == "HTML"

    async def test_a_caption_telegram_refuses_as_html_is_sent_plain(self, monkeypatch):
        bot = _telegram(monkeypatch)
        bot.send_photo.side_effect = [
            TelegramBadRequest(MagicMock(), "Bad Request: can't parse entities"),
            MagicMock(message_id=5),
        ]

        await TelegramAdapter().send_message(
            "t", OutgoingMessage(platform_chat_id="42", text="**Sales** up", image_png=b"png")
        )

        plain = bot.send_photo.await_args.kwargs
        assert plain["caption"] == "**Sales** up"
        assert plain["parse_mode"] is None

    async def test_a_files_caption_is_sent_as_html(self, monkeypatch):
        bot = _telegram(monkeypatch)

        await TelegramAdapter().send_message(
            "t",
            OutgoingMessage(
                platform_chat_id="42",
                text="**Report** attached",
                attachments=[OutgoingAttachment(filename="r.pdf", content=b"%PDF")],
            ),
        )

        sent = bot.send_document.await_args.kwargs
        assert sent["caption"] == "<b>Report</b> attached"
        assert sent["parse_mode"] == "HTML"
        bot.send_message.assert_not_awaited()

    async def test_a_chart_with_an_answer_too_long_for_a_caption_sends_the_text_first(
        self, monkeypatch
    ):
        bot = _telegram(monkeypatch)
        order: list[str] = []
        bot.send_message.side_effect = lambda **_: order.append("text") or MagicMock(message_id=5)
        bot.send_photo.side_effect = lambda **_: order.append("chart") or MagicMock(message_id=6)

        await TelegramAdapter().send_message(
            "t",
            OutgoingMessage(
                platform_chat_id="42", text="word " * 400, image_png=b"png", reply_to_message_id="9"
            ),
        )

        assert order == ["text", "chart"]
        assert bot.send_photo.await_args.kwargs["caption"] is None
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 9

    async def test_markup_does_not_count_against_a_caption(self, monkeypatch):
        """Telegram counts a caption after parsing: 1000 `&` fit, though their HTML does not."""
        bot = _telegram(monkeypatch)

        await TelegramAdapter().send_message(
            "t", OutgoingMessage(platform_chat_id="42", text="&" * 1000, image_png=b"png")
        )

        assert bot.send_photo.await_args.kwargs["caption"] == "&amp;" * 1000
        bot.send_message.assert_not_awaited()


class TestMembersOfAPrivateChat:
    """A private chat is this person and the bot: there is no list to ask Telegram for."""

    @pytest.mark.parametrize("channel_id", ["42", "42:7"])
    async def test_a_private_chat_lists_nobody_without_asking_telegram(
        self, monkeypatch: pytest.MonkeyPatch, channel_id: str
    ):
        bot = _telegram(monkeypatch)
        bot.get_chat_administrators = AsyncMock()

        with pytest.raises(ChannelDirectoryUnsupported, match="private chat"):
            await TelegramAdapter().channel_members("t", channel_id, api_base_url=None, limit=10)

        bot.get_chat_administrators.assert_not_awaited()

    @pytest.mark.parametrize("channel_id", ["-100123", "@team", "0"])
    async def test_groups_usernames_and_non_chat_ids_still_ask_for_administrators(
        self, monkeypatch: pytest.MonkeyPatch, channel_id: str
    ):
        bot = _telegram(monkeypatch)
        bot.get_chat_administrators = AsyncMock(return_value=[])

        assert (
            await TelegramAdapter().channel_members("t", channel_id, api_base_url=None, limit=10)
            == []
        )

        bot.get_chat_administrators.assert_awaited_once_with(chat_id=channel_id)
