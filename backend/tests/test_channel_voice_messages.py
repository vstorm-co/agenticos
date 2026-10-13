"""A voice note, and how it reaches the agent.

Two things have to hold together. A recording is **not** handed over as a file -
a model reads a PDF and looks at a screenshot, and an `audio/ogg` blob is a byte
count, so offering one is offering a file nobody can open. And the transcript is
**labelled**, because an agent that thinks a transcript is typed text acts on it
as if every word were certain: speech recognition mishears names, numbers and
anything said over traffic, and an agent told the source can hedge a figure it
half-heard rather than assert it.

The third thing is the one a chat makes visible: a voice note that produces no
reaction is indistinguishable from a broken bot, so a deployment that cannot
listen says so once rather than dropping the recording.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.channels.base import IncomingAttachment, IncomingMessage
from app.services.channels.router import TRANSCRIPTION_MAX_BYTES, ChannelMessageRouter

pytestmark = pytest.mark.anyio


def _voice(name: str = "voice.ogg") -> IncomingAttachment:
    return IncomingAttachment(filename=name, mime_type="audio/ogg", size=2048, handle="h")


def _document() -> IncomingAttachment:
    return IncomingAttachment(
        filename="report.pdf", mime_type="application/pdf", size=1024, handle="h2"
    )


def _incoming(*attachments: IncomingAttachment, text: str = "") -> IncomingMessage:
    return IncomingMessage(
        platform="telegram",
        bot_id=str(uuid4()),
        platform_user_id="1",
        platform_chat_id="c1",
        chat_type="private",
        text=text,
        raw={},
        attachments=list(attachments),
    )


def _bot(*, provider: str | None = "openai", model: str | None = "whisper-1") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        platform="telegram",
        speech_to_text_provider=provider,
        speech_to_text_model=model,
    )


class TestWhichAttachmentsGoWhere:
    def test_a_recording_is_separated_from_the_files(self):
        recordings, rest = ChannelMessageRouter._split_recordings(_incoming(_voice(), _document()))

        assert [a.filename for a in recordings] == ["voice.ogg"]
        assert [a.filename for a in rest] == ["report.pdf"]

    def test_a_message_with_no_audio_keeps_every_attachment(self):
        recordings, rest = ChannelMessageRouter._split_recordings(_incoming(_document()))

        assert recordings == []
        assert [a.filename for a in rest] == ["report.pdf"]

    def test_any_audio_type_counts_not_only_ogg(self):
        """Telegram invents `audio/ogg` for a voice note; an `audio` upload is
        `audio/mpeg`, and neither is readable by a model."""
        mp3 = IncomingAttachment(filename="note.mp3", mime_type="audio/mpeg", size=10, handle="h")
        recordings, rest = ChannelMessageRouter._split_recordings(_incoming(mp3))

        assert [a.filename for a in recordings] == ["note.mp3"]
        assert rest == []


class TestHowATranscriptReachesTheAgent:
    def test_it_says_that_it_is_a_transcript(self):
        """The whole point. An agent told the source can hedge a half-heard
        number; one told nothing states it as fact."""
        woven = ChannelMessageRouter._with_transcripts("", ["przelej 240 złotych"])

        assert "[Voice message, transcribed]" in woven
        assert "przelej 240 złotych" in woven

    def test_a_caption_and_a_recording_are_one_turn(self):
        """A voice note with a caption is one message somebody sent. Two turns
        would have the agent answer the caption before hearing the recording."""
        woven = ChannelMessageRouter._with_transcripts("co o tym myślisz?", ["treść nagrania"])

        assert woven.index("co o tym myślisz?") < woven.index("treść nagrania")
        assert woven.count("[Voice message, transcribed]") == 1

    def test_two_recordings_are_quoted_separately(self):
        woven = ChannelMessageRouter._with_transcripts("", ["first", "second"])

        assert woven.count("[Voice message, transcribed]") == 2

    def test_a_message_with_no_transcript_is_left_exactly_as_it_was(self):
        assert ChannelMessageRouter._with_transcripts("plain text", []) == "plain text"


class TestWhenItCannotListen:
    async def test_a_bot_with_no_model_says_so_rather_than_dropping_it(self):
        """Silence is indistinguishable from a broken bot, and the sender has no
        other way to learn that this deployment does not listen."""
        transcripts, refusals = await ChannelMessageRouter()._transcribe(
            MagicMock(), _bot(provider=None, model=None), [_voice()]
        )

        assert transcripts == []
        assert len(refusals) == 1
        assert "cannot listen" in refusals[0]

    async def test_a_message_with_no_recording_asks_nothing(self):
        transcripts, refusals = await ChannelMessageRouter()._transcribe(MagicMock(), _bot(), [])

        assert (transcripts, refusals) == ([], [])

    async def test_a_download_that_fails_costs_that_recording_only(self):
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(
            side_effect=[RuntimeError("telegram said no"), b"ogg"]
        )

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch(
                "app.services.channels.router.TranscriptionService.transcribe",
                AsyncMock(return_value="the second one"),
            ),
        ):
            transcripts, refusals = await ChannelMessageRouter()._transcribe(
                MagicMock(), _bot(), [_voice("a.ogg"), _voice("b.ogg")]
            )

        assert transcripts == ["the second one"]
        assert refusals == ["a.ogg: could not be downloaded."]

    async def test_a_recording_too_large_to_transcribe_is_refused_before_it_is_fetched(self):
        """`TranscriptionService` applies its cap to bytes already in memory, so
        the voice path buffered the whole remote file before any limit applied -
        and a channel bot is a rate-limited public surface, so one large file, or
        a few senders at once, was a worker's memory."""
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"ogg")
        huge = IncomingAttachment(
            filename="long.ogg",
            mime_type="audio/ogg",
            size=TRANSCRIPTION_MAX_BYTES + 1,
            handle="h",
        )

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
        ):
            transcripts, refusals = await ChannelMessageRouter()._transcribe(
                MagicMock(), _bot(), [huge]
            )

        adapter.download_attachment.assert_not_awaited()
        assert transcripts == []
        assert "too large to transcribe" in refusals[0]

    async def test_a_recording_at_the_limit_is_still_fetched(self):
        """The cap is a ceiling, not a margin."""
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"ogg")
        edge = IncomingAttachment(
            filename="edge.ogg", mime_type="audio/ogg", size=TRANSCRIPTION_MAX_BYTES, handle="h"
        )

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch(
                "app.services.channels.router.TranscriptionService.transcribe",
                AsyncMock(return_value="just fits"),
            ),
        ):
            transcripts, _ = await ChannelMessageRouter()._transcribe(MagicMock(), _bot(), [edge])

        assert transcripts == ["just fits"]

    async def test_a_transcription_that_fails_is_reported_not_raised(self):
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"ogg")

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch(
                "app.services.channels.router.TranscriptionService.transcribe",
                AsyncMock(return_value=None),
            ),
        ):
            transcripts, refusals = await ChannelMessageRouter()._transcribe(
                MagicMock(), _bot(), [_voice()]
            )

        assert transcripts == []
        assert refusals == ["voice.ogg: could not be transcribed."]

    async def test_the_configured_model_is_the_one_asked(self):
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"ogg")
        transcribe = AsyncMock(return_value="words")
        bot = _bot(provider="groq", model="whisper-large-v3-turbo")

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch("app.services.channels.router.TranscriptionService.transcribe", transcribe),
        ):
            await ChannelMessageRouter()._transcribe(MagicMock(), bot, [_voice()])

        assert transcribe.await_args.kwargs["provider"] == "groq"
        assert transcribe.await_args.kwargs["model"] == "whisper-large-v3-turbo"
        assert transcribe.await_args.kwargs["organization_id"] == bot.organization_id
