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

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import httpx
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

    @pytest.mark.parametrize(
        ("field", "media", "seconds"),
        [
            ("voice", {"file_id": "v", "duration": 7}, 7.0),
            ("audio", {"file_id": "a", "duration": 184, "mime_type": "audio/mpeg"}, 184.0),
            ("voice", {"file_id": "v"}, None),
            ("voice", {"file_id": "v", "duration": "7"}, None),
        ],
        ids=["voice", "audio", "no-duration", "not-a-number"],
    )
    def test_a_recordings_stated_length_is_kept_for_the_usage_record(
        self, field: str, media: dict[str, object], seconds: float | None
    ):
        """Telegram states a voice note's `duration` in whole seconds (#1797)."""
        parsed = TelegramAdapter().parse_incoming(
            {
                "message": {
                    "chat": {"id": 1, "type": "private"},
                    "from": {"id": 2},
                    field: media,
                }
            },
            "bot-1",
        )

        assert parsed is not None
        assert parsed.attachments[0].duration_seconds == seconds

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
        """Carries `subtype: file_share`, which is what Slack actually sends.

        It did not, and that is how the defect below survived a green suite: the
        whole attachment path was asserted against a payload shape the platform
        never produces.
        """
        parsed = SlackAdapter().parse_incoming(
            {
                "event": {
                    "type": "message",
                    "subtype": "file_share",
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
                    handle="https://files.slack.com/files-pri/T1-F1/download/report.csv",
                ),
            )

        assert data == b"month,total"
        assert client.get.await_args.kwargs["headers"] == {"Authorization": "Bearer xoxb-token"}

    @pytest.mark.parametrize(
        "handle",
        [
            "https://evil.example/report.csv",
            "http://files.slack.com/report.csv",
            "https://files.slack.com.evil.example/report.csv",
            "https://notslack.com/report.csv",
        ],
    )
    async def test_a_slack_download_url_off_slacks_domain_is_refused(self, handle: str):
        """The URL is the payload's, and this is the one place a payload-supplied
        address is fetched with the bot token in the header. The payload is
        signed, so this is a second lock - and a token sent to a host somebody
        else named is a token gone, so the host is Slack's or nothing is sent."""
        client = _http_client(MagicMock())

        with (
            patch("httpx.AsyncClient", return_value=client),
            pytest.raises(ValueError, match="will not send its token"),
        ):
            await SlackAdapter().download_attachment(
                "xoxb-token",
                IncomingAttachment(
                    filename="report.csv", mime_type="text/csv", size=1, handle=handle
                ),
            )

        client.get.assert_not_awaited()

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
                    filename="report.csv",
                    mime_type="text/csv",
                    size=1,
                    handle="https://files.slack.com/files-pri/T1-F1/download/report.csv",
                ),
            )


def _slack_clip(**overrides: Any) -> dict[str, Any]:
    """An audio clip recorded in Slack's composer, as Slack's file object has it.

    Shaped from the documented `file` object: `subtype: "slack_audio"` and
    `media_display_type: "audio"` mark the clip, `duration_ms` its length.
    Desktop clips are WebM; a phone's are MP4 and may be typed `video/mp4`.
    """
    clip: dict[str, Any] = {
        "id": "F0CLIP",
        "name": "audio_message.webm",
        "title": "audio_message.webm",
        "mimetype": "audio/webm",
        "filetype": "webm",
        "pretty_type": "WebM",
        "subtype": "slack_audio",
        "media_display_type": "audio",
        "duration_ms": 4120,
        "size": 45123,
        "mode": "hosted",
        "url_private": "https://files.slack.com/files-pri/T1-F0CLIP/audio_message.webm",
        "url_private_download": (
            "https://files.slack.com/files-pri/T1-F0CLIP/download/audio_message.webm"
        ),
    }
    clip.update(overrides)
    return clip


def _slack_files(*files: dict[str, Any]) -> list[IncomingAttachment]:
    parsed = SlackAdapter().parse_incoming(
        {
            "event": {
                "type": "message",
                "subtype": "file_share",
                "user": "U1",
                "channel": "D1",
                "channel_type": "im",
                "ts": "1.0",
                "files": list(files),
            }
        },
        "bot-1",
    )
    assert parsed is not None
    return parsed.attachments


class TestSlackVoiceClips:
    """Which Slack files the router will send to transcription.

    It routes on `audio/*`, so the type an attachment leaves the parser with
    decides whether a clip is heard or turned away as a file nobody can open.
    """

    def test_a_desktop_clip_is_audio_and_carries_its_length(self):
        (clip,) = _slack_files(_slack_clip())

        assert clip.mime_type == "audio/webm"
        assert clip.duration_seconds == pytest.approx(4.12)

    def test_a_phone_clip_typed_as_video_is_still_heard(self):
        """The failure the signal exists for: a recording Slack itself calls
        audio, sent with a `video/*` type the router would have stored."""
        (clip,) = _slack_files(
            _slack_clip(name="audio_message.mp4", mimetype="video/mp4", filetype="mp4")
        )

        assert clip.mime_type == "audio/mp4"

    @pytest.mark.parametrize(
        "marker", [{"media_display_type": "audio"}, {"subtype": "slack_audio"}]
    )
    def test_an_untyped_clip_named_mp4_is_heard_on_either_marker(self, marker: dict[str, str]):
        clip = _slack_clip(name="audio_message.mp4", mimetype="", filetype="mp4")
        del clip["subtype"], clip["media_display_type"]
        clip.update(marker)

        (parsed,) = _slack_files(clip)

        assert parsed.mime_type == "audio/mp4"

    def test_an_untyped_mp4_that_is_not_a_clip_is_not_transcribed(self):
        """Most likely a video: transcribing it is a billed call for a soundtrack."""
        (video,) = _slack_files(
            {
                "name": "standup.mp4",
                "mimetype": "application/octet-stream",
                "size": 900,
                "url_private_download": "https://files.slack.com/files-pri/T1-F1/standup.mp4",
            }
        )

        assert video.mime_type == "application/octet-stream"
        assert video.duration_seconds is None

    def test_a_typed_video_that_is_not_a_clip_stays_a_video(self):
        (video,) = _slack_files(
            {
                "name": "demo.mp4",
                "mimetype": "video/mp4",
                "size": 900,
                "url_private_download": "https://files.slack.com/files-pri/T1-F1/demo.mp4",
            }
        )

        assert video.mime_type == "video/mp4"

    def test_an_uploaded_audio_file_keeps_the_type_slack_gave_it(self):
        (upload,) = _slack_files(
            {
                "name": "memo.mp3",
                "mimetype": "audio/mpeg",
                "filetype": "mp3",
                "size": 900,
                "url_private_download": "https://files.slack.com/files-pri/T1-F1/memo.mp3",
            }
        )

        assert upload.mime_type == "audio/mpeg"

    def test_an_untyped_m4a_upload_is_typed_from_its_extension(self):
        (upload,) = _slack_files(
            {
                "name": "memo.m4a",
                "mimetype": "application/octet-stream",
                "size": 900,
                "url_private_download": "https://files.slack.com/files-pri/T1-F1/memo.m4a",
            }
        )

        assert upload.mime_type == "audio/mp4"

    def test_a_clip_with_no_download_url_is_skipped_and_logged(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Never answered, so the log line is the only trace it arrived."""
        clip = _slack_clip()
        del clip["url_private"], clip["url_private_download"]

        with caplog.at_level("INFO", logger="app.services.channels.slack"):
            parsed = SlackAdapter().parse_incoming(
                {"event": {"type": "message", "user": "U1", "channel": "D1", "files": [clip]}},
                "bot-1",
            )

        assert parsed is None
        assert "file=F0CLIP recording=True" in caplog.text


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


class TestMattermostVoiceFiles:
    """Mattermost types most uploads itself; an untyped one is typed here."""

    @staticmethod
    def _parsed(entry: dict[str, Any]) -> IncomingAttachment:
        adapter = MattermostAdapter()
        adapter.remember_server("bot-1", "https://mm.test")
        post = {
            "id": "p1",
            "user_id": "u1",
            "channel_id": "c1",
            "message": "",
            "file_ids": ["f1"],
            "metadata": {"files": [{"id": "f1", "size": 2048, **entry}]},
        }
        parsed = adapter.parse_incoming(
            {"event": "posted", "data": {"channel_type": "D", "post": json.dumps(post)}},
            "bot-1",
        )
        assert parsed is not None
        return parsed.attachments[0]

    def test_a_typed_audio_file_keeps_its_type(self):
        upload = self._parsed({"name": "memo.m4a", "extension": "m4a", "mime_type": "audio/x-m4a"})

        assert upload.mime_type == "audio/x-m4a"

    def test_an_octet_stream_mp3_is_heard(self):
        upload = self._parsed(
            {"name": "memo.mp3", "extension": "mp3", "mime_type": "application/octet-stream"}
        )

        assert upload.mime_type == "audio/mpeg"

    def test_a_name_with_no_extension_is_typed_from_the_extension_field(self):
        upload = self._parsed({"name": "voice note", "extension": "ogg", "mime_type": ""})

        assert upload.mime_type == "audio/ogg"

    def test_an_untyped_file_with_no_audio_extension_stays_untyped(self):
        upload = self._parsed({"name": "dump.bin", "extension": "bin"})

        assert upload.mime_type == "application/octet-stream"


class TestMattermostWebhookFiles:
    """An outgoing webhook names its files by id; the details are looked up."""

    @staticmethod
    def _webhook_files() -> list[IncomingAttachment]:
        adapter = MattermostAdapter()
        adapter.remember_server("bot-1", "https://mm.test")
        parsed = adapter.parse_incoming(
            {"user_id": "u1", "user_name": "ada", "channel_id": "c1", "file_ids": "f1"},
            "bot-1",
        )
        assert parsed is not None
        return parsed.attachments

    async def test_a_file_named_by_id_alone_is_described_and_heard(self):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(
            return_value={
                "id": "f1",
                "name": "memo.mp3",
                "extension": "mp3",
                "mime_type": "application/octet-stream",
                "size": 2048,
            }
        )
        attachments = self._webhook_files()

        with patch("httpx.AsyncClient", return_value=_http_client(response)) as client_factory:
            (described,) = await MattermostAdapter().describe_attachments("token", attachments)

        assert (described.filename, described.mime_type, described.size) == (
            "memo.mp3",
            "audio/mpeg",
            2048,
        )
        assert described.handle == "https://mm.test/api/v4/files/f1"
        get = client_factory.return_value.get.await_args
        assert get.args[0] == "https://mm.test/api/v4/files/f1/info"
        assert get.kwargs["headers"]["Authorization"] == "Bearer token"

    async def test_a_lookup_that_fails_keeps_the_file_as_an_ordinary_attachment(self):
        attachments = self._webhook_files()
        client = _http_client(None)
        client.get = AsyncMock(side_effect=httpx.ConnectError("down"))

        with patch("httpx.AsyncClient", return_value=client):
            described = await MattermostAdapter().describe_attachments("token", attachments)

        assert described == attachments

    @pytest.mark.parametrize(
        "answer",
        [
            ["not", "an", "object"],
            {"name": "memo.mp3", "mime_type": "audio/mpeg", "size": "large"},
            {"name": "memo.mp3", "mime_type": "audio/mpeg", "size": [2048]},
            {"name": "memo.mp3", "mime_type": "audio/mpeg", "size": float("inf")},
        ],
        ids=["a-list", "size-a-word", "size-a-list", "size-not-finite"],
    )
    async def test_a_malformed_answer_keeps_the_file_rather_than_dropping_the_turn(
        self, answer: object
    ):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value=answer)
        attachments = self._webhook_files()

        with patch("httpx.AsyncClient", return_value=_http_client(response)):
            described = await MattermostAdapter().describe_attachments("token", attachments)

        assert described == attachments

    async def test_a_type_or_extension_that_is_not_text_is_not_trusted(self):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(
            return_value={"name": "memo.mp3", "mime_type": 7, "extension": ["mp3"], "size": 9}
        )

        with patch("httpx.AsyncClient", return_value=_http_client(response)):
            (described,) = await MattermostAdapter().describe_attachments(
                "token", self._webhook_files()
            )

        # Typed from the name alone, as an untyped upload is.
        assert (described.mime_type, described.size) == ("audio/mpeg", 9)

    async def test_several_files_are_looked_up_together_and_kept_in_order(self):
        adapter = MattermostAdapter()
        adapter.remember_server("bot-1", "https://mm.test")
        parsed = adapter.parse_incoming(
            {"user_id": "u1", "user_name": "ada", "channel_id": "c1", "file_ids": "f1,f2,f3"},
            "bot-1",
        )
        assert parsed is not None
        in_flight = 0
        widest = 0

        async def info(url: str, **_: object) -> MagicMock:
            nonlocal in_flight, widest
            in_flight += 1
            widest = max(widest, in_flight)
            await anyio.sleep(0.01)
            in_flight -= 1
            file_id = url.rsplit("/", 2)[-2]
            response = MagicMock()
            response.raise_for_status = MagicMock()
            response.json = MagicMock(
                return_value={"name": f"{file_id}.ogg", "mime_type": "audio/ogg", "size": 1}
            )
            return response

        client = _http_client(None)
        client.get = AsyncMock(side_effect=info)
        with patch("httpx.AsyncClient", return_value=client):
            described = await MattermostAdapter().describe_attachments("token", parsed.attachments)

        assert [one.filename for one in described] == ["f1.ogg", "f2.ogg", "f3.ogg"]
        assert widest > 1

    async def test_a_file_the_event_described_is_not_asked_about(self):
        described = IncomingAttachment(
            filename="memo.mp3",
            mime_type="audio/mpeg",
            size=10,
            handle="https://mm.test/api/v4/files/f1",
        )

        with patch("httpx.AsyncClient", return_value=_http_client(None)) as client_factory:
            found = await MattermostAdapter().describe_attachments("token", [described])

        assert found == [described]
        client_factory.return_value.get.assert_not_awaited()

    async def test_a_platform_that_sends_the_details_keeps_them(self):
        clip = IncomingAttachment(filename="a.webm", mime_type="audio/webm", size=1, handle="h")

        assert await SlackAdapter().describe_attachments("token", [clip]) == [clip]


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


class TestWhichSlackSubtypesAreSomebodyTalking:
    """Slack stamps a `subtype` for two unrelated reasons, and the adapter refused
    all of them - so a message with an image attached was dropped whole, caption
    included, before `_attachments` ever ran. The attachment path was written,
    tested and unreachable on this platform.
    """

    @staticmethod
    def _event(**extra: object) -> dict[str, object]:
        return {
            "event": {
                "type": "message",
                "user": "U1",
                "channel": "D1",
                "channel_type": "im",
                "ts": "1.0",
                "text": "co widzisz?",
                **extra,
            }
        }

    def test_a_photo_with_a_caption_arrives_with_both(self):
        """The reported defect: a question asked about an attached image, in a DM,
        answered as though the message had been empty."""
        parsed = SlackAdapter().parse_incoming(
            self._event(
                subtype="file_share",
                files=[
                    {
                        "name": "screenshot.png",
                        "mimetype": "image/png",
                        "size": 2048,
                        "url_private_download": "https://files.slack.test/screenshot.png",
                    }
                ],
            ),
            "bot-1",
        )

        assert parsed is not None
        assert parsed.text == "co widzisz?"
        assert len(parsed.attachments) == 1
        assert parsed.attachments[0].filename == "screenshot.png"

    def test_a_plain_message_with_no_subtype_still_arrives(self):
        parsed = SlackAdapter().parse_incoming(self._event(), "bot-1")

        assert parsed is not None
        assert parsed.text == "co widzisz?"

    @pytest.mark.parametrize(
        "subtype",
        ["message_changed", "message_deleted", "channel_join", "channel_topic", "bot_message"],
    )
    def test_the_platform_describing_the_channel_is_not(self, subtype: str):
        """These are the ones the guard exists for, and they stay refused. An edit
        answered again is the same question twice, and a join is not a question."""
        assert SlackAdapter().parse_incoming(self._event(subtype=subtype), "bot-1") is None

    def test_a_thread_broadcast_is_left_out_deliberately(self):
        """A thread reply also posted to the channel, so it arrives beside the
        reply itself - answering both would be answering twice."""
        assert (
            SlackAdapter().parse_incoming(self._event(subtype="thread_broadcast"), "bot-1") is None
        )

    def test_the_bots_own_message_is_refused_whatever_its_subtype(self):
        """Answering it is a loop, and each turn is a model call."""
        assert (
            SlackAdapter().parse_incoming(self._event(subtype="file_share", bot_id="B1"), "bot-1")
            is None
        )


class TestSlackReadsAThreadsEarlierFiles:
    """The transcript alone was not enough, and the bot said so accurately: asked
    "what do you see" about a screenshot posted one message earlier, it answered
    that it could see no image in the conversation - only the text. It was right,
    which is how a missing half announces itself rather than a broken one.
    """

    @staticmethod
    def _client(*messages: dict[str, Any]) -> Any:
        client = MagicMock()
        client.conversations_replies = AsyncMock(return_value={"messages": list(messages)})
        return client

    async def test_a_photo_posted_before_the_bot_arrived_comes_back_as_a_handle(self):
        client = self._client(
            {
                "user": "U1",
                "text": "co tu widzisz",
                "subtype": "file_share",
                "files": [
                    {
                        "name": "screenshot.png",
                        "mimetype": "image/png",
                        "size": 2048,
                        "url_private_download": "https://files.slack.test/screenshot.png",
                    }
                ],
            },
            {"user": "U1", "text": "@Jarvis"},
        )

        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=client):
            found = await SlackAdapter().thread_attachments(
                "tok", "C1", thread_id="1699.0001", api_base_url=None, limit=50
            )

        assert [a.filename for a in found] == ["screenshot.png"]
        assert found[0].handle == "https://files.slack.test/screenshot.png"

    async def test_the_bots_own_uploads_are_not_read_back(self):
        """It posts charts and files of its own; feeding them back as somebody's
        attachment would have the agent answering about its own output."""
        client = self._client(
            {
                "bot_id": "B1",
                "text": "here is the chart",
                "files": [
                    {
                        "name": "chart.png",
                        "mimetype": "image/png",
                        "size": 10,
                        "url_private_download": "https://files.slack.test/chart.png",
                    }
                ],
            }
        )

        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=client):
            found = await SlackAdapter().thread_attachments(
                "tok", "C1", thread_id="1699.0001", api_base_url=None, limit=50
            )

        assert found == []

    async def test_a_thread_of_plain_messages_costs_nothing_downstream(self):
        client = self._client({"user": "U1", "text": "just talking"})

        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=client):
            found = await SlackAdapter().thread_attachments(
                "tok", "C1", thread_id="1699.0001", api_base_url=None, limit=50
            )

        assert found == []

    async def test_a_platform_without_threads_refuses_rather_than_answering_empty(self):
        """The base is what Telegram and anything new gets: an empty list would be
        a claim that the thread has no files."""
        from app.services.channels.base import ChannelDirectoryUnsupported
        from app.services.channels.telegram import TelegramAdapter

        with pytest.raises(ChannelDirectoryUnsupported):
            await TelegramAdapter().thread_attachments(
                "tok", "C1", thread_id="x", api_base_url=None, limit=5
            )
