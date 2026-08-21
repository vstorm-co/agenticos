"""What each adapter makes of a message with a file on it.

Three platforms, one behaviour, and it is the behaviour that was missing: a
message with a file and no caption used to parse as `None`, so a spreadsheet
dropped into a channel was discarded and the agent answered about a document it
never received. Every adapter now treats "no text but a file" as a message.

The rest is per-platform and none of it is guessable from the others. Telegram
sends a `file_id` that has to be resolved through `getFile` and gives photos as a
list of sizes; Slack puts a private URL on the event that answers with a sign-in
*page* rather than a 401 if the token is missing; Mattermost is somebody's own
server, so the id alone cannot be fetched at all.

These adapters are template-inherited and outside the 100% gate, but this is the
path where a bug means a file silently dropped with nothing logged - which is
exactly the failure the feature exists to fix.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Chat
from aiogram.types import Message as AiogramMessage
from aiogram.types import User as AiogramUser

from app.services.channels.base import (
    IncomingAttachment,
    IncomingMessage,
    OutgoingAttachment,
    OutgoingMessage,
)
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.slack import SlackAdapter
from app.services.channels.telegram import TelegramAdapter

pytestmark = pytest.mark.anyio


def _polled(**fields: Any) -> AiogramMessage:
    """One update as aiogram hands it to the polling loop's handler."""
    fields.setdefault("from_user", AiogramUser(id=9, is_bot=False, first_name="Ada"))
    return AiogramMessage(
        message_id=7,
        date=datetime(2026, 8, 13, tzinfo=UTC),
        chat=Chat(id=42, type="private"),
        **fields,
    )


async def _routed(message: AiogramMessage) -> IncomingMessage | None:
    """What the polling path hands the router, or `None` if it handed it nothing."""
    router = MagicMock(route=AsyncMock())
    context = MagicMock(__aenter__=AsyncMock(return_value=MagicMock()), __aexit__=AsyncMock())

    with (
        patch("app.services.channels.telegram.ChannelMessageRouter", return_value=router),
        patch("app.services.channels.telegram.get_db_context", return_value=context),
    ):
        await TelegramAdapter()._handle_update(message, "bot-1")

    if not router.route.await_args_list:
        return None
    routed = router.route.await_args.args[0]
    assert isinstance(routed, IncomingMessage)
    return routed


class TestTelegramReceiving:
    def test_a_document_with_no_caption_is_still_a_message(self):
        parsed = TelegramAdapter().parse_incoming(
            {
                "message": {
                    "message_id": 7,
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": 9, "first_name": "Ada"},
                    "document": {
                        "file_id": "BQACAgQ",
                        "file_name": "report.csv",
                        "mime_type": "text/csv",
                        "file_size": 128,
                    },
                }
            },
            "bot-1",
        )

        assert parsed is not None
        assert parsed.text == ""
        assert [a.filename for a in parsed.attachments] == ["report.csv"]
        assert parsed.attachments[0].handle == "BQACAgQ"

    def test_a_caption_becomes_the_text(self):
        parsed = TelegramAdapter().parse_incoming(
            {
                "message": {
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": 9},
                    "caption": "what is in here?",
                    "document": {"file_id": "x", "file_name": "a.csv", "mime_type": "text/csv"},
                }
            },
            "bot-1",
        )

        assert parsed is not None
        assert parsed.text == "what is in here?"

    def test_the_largest_photo_is_the_one_worth_having(self):
        """Telegram sends the same image in several sizes; the rest are thumbnails
        it generated."""
        parsed = TelegramAdapter().parse_incoming(
            {
                "message": {
                    "chat": {"id": 1, "type": "private"},
                    "from": {"id": 2},
                    "photo": [
                        {"file_id": "small", "file_unique_id": "s", "file_size": 100},
                        {"file_id": "large", "file_unique_id": "l", "file_size": 9000},
                    ],
                }
            },
            "bot-1",
        )

        assert parsed is not None
        assert parsed.attachments[0].handle == "large"
        # Telegram sends no MIME type for a photo, and every entry is a JPEG.
        assert parsed.attachments[0].mime_type == "image/jpeg"

    @pytest.mark.parametrize(
        ("field", "payload", "filename", "mime"),
        [
            ("voice", {"file_id": "v", "duration": 7}, "voice.ogg", "audio/ogg"),
            ("audio", {"file_id": "a", "file_name": "song.mp3"}, "song.mp3", "audio/mpeg"),
            ("video", {"file_id": "m"}, "video.mp4", "video/mp4"),
            ("video_note", {"file_id": "n"}, "video-note.mp4", "video/mp4"),
        ],
    )
    def test_every_kind_of_media_telegram_sends_is_seen(
        self, field: str, payload: dict, filename: str, mime: str
    ):
        """Telegram puts each kind in its own field, and a message carrying only one
        has no text - which is why a voice note used to parse as nothing and vanish
        without a log line."""
        parsed = TelegramAdapter().parse_incoming(
            {"message": {"chat": {"id": 1, "type": "private"}, "from": {"id": 2}, field: payload}},
            "bot-1",
        )

        assert parsed is not None
        assert parsed.attachments[0].filename == filename
        assert parsed.attachments[0].mime_type == mime

    def test_a_message_with_neither_text_nor_a_file_is_still_nothing(self):
        assert (
            TelegramAdapter().parse_incoming(
                {"message": {"chat": {"id": 1, "type": "private"}, "from": {"id": 2}}}, "bot-1"
            )
            is None
        )

    def test_a_message_with_no_sender_is_nothing_on_this_transport_too(self):
        """The polling loop always refused one. The webhook parser answered it with
        an empty `platform_user_id`, which is a single identity shared by every
        senderless post the bot ever sees (#547)."""
        assert (
            TelegramAdapter().parse_incoming(
                {"message": {"chat": {"id": 1, "type": "supergroup"}, "text": "hello"}}, "bot-1"
            )
            is None
        )

    def test_a_document_with_no_name_gets_one_rather_than_an_empty_path(self):
        parsed = TelegramAdapter().parse_incoming(
            {
                "message": {
                    "chat": {"id": 1, "type": "private"},
                    "from": {"id": 2},
                    "document": {"file_id": "x"},
                }
            },
            "bot-1",
        )

        assert parsed is not None
        assert parsed.attachments[0].filename == "file"
        assert parsed.attachments[0].mime_type == "application/octet-stream"

    async def test_downloading_resolves_the_id_and_then_fetches(self):
        """Two requests because that is Telegram's design: a `file_id` is not a URL
        and the path it resolves to expires, so resolving it at parse time would
        hand the router a stale link."""
        bot = MagicMock()
        bot.get_file = AsyncMock(return_value=MagicMock(file_path="documents/report.csv"))
        bot.download_file = AsyncMock(return_value=MagicMock(read=lambda: b"month,total"))
        bot.session.close = AsyncMock()

        with patch("app.services.channels.telegram.Bot", return_value=bot):
            data = await TelegramAdapter().download_attachment(
                "token",
                IncomingAttachment(filename="report.csv", mime_type="text/csv", size=1, handle="f"),
            )

        assert data == b"month,total"
        assert bot.get_file.await_args.args[0] == "f"
        bot.session.close.assert_awaited_once()

    async def test_a_file_telegram_will_not_resolve_is_an_error_not_empty_bytes(self):
        bot = MagicMock()
        bot.get_file = AsyncMock(return_value=MagicMock(file_path=None))
        bot.session.close = AsyncMock()

        with (
            patch("app.services.channels.telegram.Bot", return_value=bot),
            pytest.raises(ValueError, match="no path"),
        ):
            await TelegramAdapter().download_attachment(
                "token",
                IncomingAttachment(filename="a", mime_type="text/csv", size=1, handle="f"),
            )

        bot.session.close.assert_awaited_once()


class TestTelegramPolling:
    """The second way in, which used to be a second parser (#547).

    Polling is the self-hosted and development mode, and its handler built an
    `IncomingMessage` of its own: text only, `raw={}`, and no call to
    `_attachments` at all. So a file dropped on a Telegram bot that was not on a
    webhook was discarded exactly the way #113 had already fixed for the webhook,
    and the agent answered about a document it never received.
    """

    async def test_a_document_sent_to_a_polling_bot_reaches_the_router(self):
        routed = await _routed(
            _polled(
                document={
                    "file_id": "BQACAgQ",
                    "file_unique_id": "u",
                    "file_name": "report.csv",
                    "mime_type": "text/csv",
                    "file_size": 128,
                }
            )
        )

        assert routed is not None
        assert [a.filename for a in routed.attachments] == ["report.csv"]
        assert routed.attachments[0].handle == "BQACAgQ"

    async def test_a_caption_is_the_text_here_too(self):
        """A photo with a caption had no `text`, so the whole message was dropped -
        the question about the picture along with the picture."""
        routed = await _routed(
            _polled(
                caption="what is wrong with this chart",
                photo=[{"file_id": "small", "file_unique_id": "s", "width": 1, "height": 1}],
            )
        )

        assert routed is not None
        assert routed.text == "what is wrong with this chart"
        assert routed.attachments[0].handle == "small"

    async def test_the_update_is_carried_whole_rather_than_thrown_away(self):
        routed = await _routed(_polled(text="hello"))

        assert routed is not None
        assert routed.text == "hello"
        assert routed.raw["message"]["message_id"] == 7

    async def test_a_message_with_neither_text_nor_a_file_is_not_routed(self):
        assert await _routed(_polled()) is None

    async def test_a_message_with_no_sender_is_not_routed(self):
        """The Bot API leaves `from` empty for a message sent to a channel, and a
        run needs somebody to be. Polling always refused one; the webhook parser
        did not, and keyed a shared identity on an empty user id instead."""
        assert await _routed(_polled(text="hello", from_user=None)) is None

    async def test_a_sender_with_no_surname_is_not_displayed_as_ada_none(self):
        """`exclude_none` on the dump, in one assertion. aiogram holds a `None`
        where Telegram simply omits the field, and the display name is built by
        joining the two - so leaving it in renames everybody without a surname."""
        routed = await _routed(_polled(text="hello"))

        assert routed is not None
        assert routed.platform_display_name == "Ada"


class TestTelegramSending:
    async def test_files_are_posted_with_the_answer_as_the_first_caption(self):
        """So the answer and the file it is about arrive together rather than as
        two messages about different things."""
        bot = MagicMock()
        bot.send_document = AsyncMock()
        bot.send_message = AsyncMock()
        bot.session.close = AsyncMock()

        with patch("app.services.channels.telegram.Bot", return_value=bot):
            await TelegramAdapter().send_message(
                "token",
                OutgoingMessage(
                    platform_chat_id="42",
                    text="here is the report",
                    attachments=[
                        OutgoingAttachment(filename="a.csv", content=b"a"),
                        OutgoingAttachment(filename="b.csv", content=b"b"),
                    ],
                ),
            )

        assert bot.send_document.await_count == 2
        assert bot.send_document.await_args_list[0].kwargs["caption"] == "here is the report"
        assert bot.send_document.await_args_list[1].kwargs["caption"] is None
        bot.send_message.assert_not_called()

    async def test_an_answer_too_long_for_a_caption_is_sent_as_a_message_first(self):
        """Telegram caps a caption at 1024 characters, and truncating an agent's
        answer to fit would lose the part somebody asked for."""
        bot = MagicMock()
        bot.send_document = AsyncMock()
        bot.send_message = AsyncMock()
        bot.session.close = AsyncMock()

        with patch("app.services.channels.telegram.Bot", return_value=bot):
            await TelegramAdapter().send_message(
                "token",
                OutgoingMessage(
                    platform_chat_id="42",
                    text="x" * 2000,
                    attachments=[OutgoingAttachment(filename="a.csv", content=b"a")],
                ),
            )

        bot.send_message.assert_awaited_once()
        assert bot.send_document.await_args.kwargs["caption"] is None


class TestSlackReceiving:
    def test_a_file_with_no_text_is_still_a_message(self):
        parsed = SlackAdapter().parse_incoming(
            {
                "event": {
                    "type": "message",
                    "user": "U1",
                    "channel": "C1",
                    "ts": "1.0",
                    "files": [
                        {
                            "name": "report.csv",
                            "mimetype": "text/csv",
                            "size": 128,
                            "url_private_download": "https://files.slack.test/report.csv",
                        }
                    ],
                }
            },
            "bot-1",
        )

        assert parsed is not None
        assert parsed.text == ""
        assert parsed.attachments[0].handle == "https://files.slack.test/report.csv"

    def test_a_file_still_being_processed_is_skipped_rather_than_failed(self):
        """It has no download URL yet and arrives again when Slack is done with it;
        treating that as an error would report a failure for something merely not
        ready."""
        parsed = SlackAdapter().parse_incoming(
            {
                "event": {
                    "type": "message",
                    "user": "U1",
                    "channel": "C1",
                    "text": "here",
                    "files": [{"name": "pending.csv", "mimetype": "text/csv"}],
                }
            },
            "bot-1",
        )

        assert parsed is not None
        assert parsed.attachments == []

    def test_something_that_is_not_a_file_entry_is_ignored(self):
        parsed = SlackAdapter().parse_incoming(
            {"event": {"type": "message", "user": "U1", "channel": "C1", "files": ["nonsense"]}},
            "bot-1",
        )

        assert parsed is None

    async def test_the_bot_token_is_sent_with_the_download(self):
        response = MagicMock(headers={"content-type": "text/csv"}, content=b"month,total")
        response.raise_for_status = MagicMock()
        client = _http_client(response)

        with patch("httpx.AsyncClient", return_value=client):
            data = await SlackAdapter().download_attachment(
                "xoxb-token",
                IncomingAttachment(
                    filename="report.csv",
                    mime_type="text/csv",
                    size=1,
                    handle="https://files.slack.test/report.csv",
                ),
            )

        assert data == b"month,total"
        assert client.get.await_args.kwargs["headers"] == {"Authorization": "Bearer xoxb-token"}

    async def test_a_sign_in_page_is_refused_rather_than_stored_as_the_file(self):
        """Slack answers 200 with HTML rather than 401 when the token cannot read a
        file, so without this the user's spreadsheet becomes a login page."""
        response = MagicMock(
            headers={"content-type": "text/html; charset=utf-8"}, content=b"<html>"
        )
        response.raise_for_status = MagicMock()

        with (
            patch("httpx.AsyncClient", return_value=_http_client(response)),
            pytest.raises(ValueError, match="sign-in page"),
        ):
            await SlackAdapter().download_attachment(
                "xoxb-token",
                IncomingAttachment(
                    filename="report.csv", mime_type="text/csv", size=1, handle="https://x/y"
                ),
            )


class TestSlackSending:
    async def test_files_and_the_answer_are_one_message(self):
        client = MagicMock(files_upload_v2=AsyncMock(), chat_postMessage=AsyncMock())

        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=client):
            await SlackAdapter().send_message(
                "xoxb",
                OutgoingMessage(
                    platform_chat_id="C1:1.0",
                    text="here is the report",
                    attachments=[OutgoingAttachment(filename="a.csv", content=b"a")],
                ),
            )

        client.chat_postMessage.assert_not_called()
        kwargs = client.files_upload_v2.await_args.kwargs
        assert kwargs["initial_comment"] == "here is the report"
        assert kwargs["thread_ts"] == "1.0"
        assert kwargs["file_uploads"][0]["filename"] == "a.csv"


class TestMattermostReceiving:
    def test_a_post_with_a_file_and_no_message_is_still_a_message(self):
        adapter = MattermostAdapter()
        adapter.remember_server("bot-1", "https://mm.test/")

        parsed = adapter.parse_incoming(
            {
                "event": "posted",
                "data": {
                    "channel_type": "O",
                    "sender_name": "@ada",
                    "post": (
                        '{"id": "p1", "user_id": "u1", "channel_id": "c1", "message": "", '
                        '"file_ids": ["f1"], "metadata": {"files": [{"id": "f1", '
                        '"name": "report.csv", "mime_type": "text/csv", "size": 128}]}}'
                    ),
                },
            },
            "bot-1",
        )

        assert parsed is not None
        assert parsed.attachments[0].filename == "report.csv"
        assert parsed.attachments[0].handle == "https://mm.test/api/v4/files/f1"

    def test_a_file_with_no_metadata_claims_nothing_and_is_checked_after_the_download(self):
        adapter = MattermostAdapter()
        adapter.remember_server("bot-1", "https://mm.test")

        parsed = adapter.parse_incoming(
            {
                "event": "posted",
                "data": {
                    "channel_type": "D",
                    "post": '{"id": "p1", "user_id": "u1", "channel_id": "c1", "file_ids": ["f9"]}',
                },
            },
            "bot-1",
        )

        assert parsed is not None
        assert parsed.attachments[0].filename == "f9"
        assert parsed.attachments[0].size == 0

    def test_a_bot_whose_server_is_unknown_carries_no_handle(self):
        parsed = MattermostAdapter().parse_incoming(
            {
                "event": "posted",
                "data": {
                    "channel_type": "D",
                    "post": '{"id": "p1", "user_id": "u1", "channel_id": "c1", "file_ids": ["f1"]}',
                },
            },
            "unknown-bot",
        )

        assert parsed is not None
        assert parsed.attachments[0].handle == ""

    def test_an_outgoing_webhook_post_carries_its_files_too(self):
        """The second way into this adapter, and it read no files at all (#547).

        The webhook body spells `file_ids` as one comma-separated string where the
        socket sends a list, which is the whole reason handing the flat payload to
        the shared reader was never enough.
        """
        adapter = MattermostAdapter()
        adapter.remember_server("bot-1", "https://mm.test")

        parsed = adapter.parse_incoming(
            {
                "user_id": "u1",
                "user_name": "ada",
                "channel_id": "c1",
                "channel_name": "town-square",
                "text": "what does this say",
                "file_ids": "f1,f2",
            },
            "bot-1",
        )

        assert parsed is not None
        assert [a.filename for a in parsed.attachments] == ["f1", "f2"]
        assert parsed.attachments[0].handle == "https://mm.test/api/v4/files/f1"

    def test_a_webhook_post_with_a_file_and_no_text_is_still_a_message(self):
        parsed = MattermostAdapter().parse_incoming(
            {"user_id": "u1", "user_name": "ada", "channel_id": "c1", "file_ids": "f1"},
            "bot-1",
        )

        assert parsed is not None
        assert parsed.text == ""
        assert [a.filename for a in parsed.attachments] == ["f1"]

    def test_a_webhook_post_with_no_files_says_so_rather_than_one_empty_id(self):
        parsed = MattermostAdapter().parse_incoming(
            {"user_id": "u1", "user_name": "ada", "channel_id": "c1", "text": "hi", "file_ids": ""},
            "bot-1",
        )

        assert parsed is not None
        assert parsed.attachments == []

    async def test_a_missing_server_is_reported_rather_than_guessed_at(self):
        """Guessing a Mattermost address is guessing which company's server to send
        a bot token to."""
        with pytest.raises(ValueError, match="no server URL"):
            await MattermostAdapter().download_attachment(
                "token",
                IncomingAttachment(filename="a", mime_type="text/csv", size=1, handle=""),
            )

    async def test_downloading_uses_the_url_the_parser_resolved(self):
        response = MagicMock(content=b"month,total")
        response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient", return_value=_http_client(response)) as client_factory:
            data = await MattermostAdapter().download_attachment(
                "token",
                IncomingAttachment(
                    filename="a.csv",
                    mime_type="text/csv",
                    size=1,
                    handle="https://mm.test/api/v4/files/f1",
                ),
            )

        assert data == b"month,total"
        assert (
            client_factory.return_value.get.await_args.args[0] == "https://mm.test/api/v4/files/f1"
        )


class TestMattermostSending:
    async def test_the_chart_and_the_files_are_uploaded_together(self):
        """Mattermost attaches files to a post by id, so both halves are one call
        and a post referencing them follows."""
        upload = MagicMock(json=lambda: {"file_infos": [{"id": "f1"}, {"id": "f2"}]})
        upload.raise_for_status = MagicMock()
        post = MagicMock()
        post.raise_for_status = MagicMock()
        client = MagicMock()
        client.post = AsyncMock(side_effect=[upload, post])
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=client):
            await MattermostAdapter().send_message(
                "token",
                OutgoingMessage(
                    platform_chat_id="c1",
                    text="here it is",
                    api_base_url="https://mm.test",
                    image_png=b"png",
                    attachments=[OutgoingAttachment(filename="a.csv", content=b"a")],
                ),
            )

        files = client.post.await_args_list[0].kwargs["files"]
        assert [name for name, _ in files] == ["files", "files"]
        assert client.post.await_args_list[1].kwargs["json"]["file_ids"] == ["f1", "f2"]


def _http_client(response: Any) -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


async def test_an_upload_is_not_posted_back_whichever_backend_holds_it(tmp_path) -> None:
    """The snapshot is taken before the attachment router writes, so a person's own
    upload looks like a file the turn produced - and this exclusion is the only
    thing between that and a reply posting somebody's PDF back at them as the
    agent's work.

    A stored workspace's paths begin with `/` and a container's come back from the
    host's `ls` relative, so a tuple of `/uploads/` matched one and not the other.
    """
    from app.services.channels.attachments import _NOT_THE_AGENTS

    for path in ("uploads/8b1e-report.pdf", "/uploads/8b1e-report.pdf"):
        assert path.lstrip("/").startswith(_NOT_THE_AGENTS)

    assert not "reports/summary.csv".lstrip("/").startswith(_NOT_THE_AGENTS)
