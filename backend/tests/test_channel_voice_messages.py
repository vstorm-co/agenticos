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

import json
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ExternalServiceError
from app.services.channels.base import IncomingAttachment, IncomingMessage
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.router import TRANSCRIPTION_MAX_BYTES, ChannelMessageRouter
from app.services.channels.slack import SlackAdapter

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


def _bot(
    *,
    provider: str | None = "openai",
    model: str | None = "whisper-1",
    transcribe: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        platform="telegram",
        transcribe_voice_notes=transcribe,
        speech_to_text_provider=provider,
        speech_to_text_model=model,
    )


_SETTINGS = "app.services.speech_to_text_settings"


@pytest.fixture(autouse=True)
def world() -> Iterator[SimpleNamespace]:
    """What the resolver reads: one agent bound to the bot, and an organization.

    Neither names an engine by default, so a test that wants one says which
    level it lives on - the bot, the agent's published spec, or the organization.
    """
    agent = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        name="Support",
        status="published",
        current_version_id=uuid4(),
    )
    state = SimpleNamespace(
        exposed=[(SimpleNamespace(environment_id=None), agent)],
        org=SimpleNamespace(
            speech_to_text_provider=None,
            speech_to_text_model=None,
            speech_to_text_language=None,
        ),
        spec={"name": "Support"},
    )
    with (
        patch(
            f"{_SETTINGS}.agent_exposure_repo.list_active_for_bot",
            new=AsyncMock(side_effect=lambda *_a, **_k: state.exposed),
        ),
        patch(
            f"{_SETTINGS}.organization_repo.get_by_id",
            new=AsyncMock(side_effect=lambda *_a, **_k: state.org),
        ),
        patch(
            f"{_SETTINGS}.agent_repo.get_version",
            new=AsyncMock(side_effect=lambda *_a, **_k: SimpleNamespace(spec=state.spec)),
        ),
    ):
        yield state


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

    def test_each_recording_is_logged_with_its_type_and_name(
        self, caplog: pytest.LogCaptureFixture
    ):
        """The line a live failure is diagnosed from: what the platform called
        the recording, and that it went to transcription."""
        with caplog.at_level("INFO", logger="app.services.channels.router"):
            ChannelMessageRouter._split_recordings(_incoming(_voice("note.opus"), _document()))

        assert "type=audio/ogg filename=note.opus" in caplog.text
        assert "report.pdf" not in caplog.text


class TestWhatTheProviderIsSent:
    """OpenAI and Groq read the format from the file name, not the type."""

    @pytest.mark.parametrize(
        ("name", "claimed", "sent_name", "sent_type"),
        [
            ("audio", "audio/ogg", "voice.ogg", "audio/ogg"),
            ("note.opus", "audio/ogg; codecs=opus", "voice.ogg", "audio/ogg"),
            ("audio_message.mp4", "audio/mp4", "voice.m4a", "audio/mp4"),
            ("memo.m4a", "audio/x-m4a", "voice.m4a", "audio/mp4"),
            ("memo", "audio/mp3", "voice.mp3", "audio/mpeg"),
            ("take.wav", "audio/x-wav", "voice.wav", "audio/wav"),
            ("audio_message.webm", "audio/webm", "voice.webm", "audio/webm"),
        ],
    )
    def test_the_name_follows_the_type(
        self, name: str, claimed: str, sent_name: str, sent_type: str
    ):
        attachment = IncomingAttachment(filename=name, mime_type=claimed, size=3, handle="h")

        sent = ChannelMessageRouter._as_sent(attachment, b"abc")

        assert (sent.filename, sent.mime_type, sent.content) == (sent_name, sent_type, b"abc")

    def test_a_type_with_no_known_extension_keeps_its_own_name(self):
        """Still audio; whether the provider reads FLAC is the provider's to say."""
        attachment = IncomingAttachment(
            filename="take.flac", mime_type="audio/flac", size=3, handle="h"
        )

        sent = ChannelMessageRouter._as_sent(attachment, b"abc")

        assert (sent.filename, sent.mime_type) == ("take.flac", "audio/flac")


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
    async def test_a_bot_with_nothing_to_inherit_says_so_rather_than_dropping_it(self):
        """Silence is indistinguishable from a broken bot, and the sender has no
        other way to learn that this deployment does not listen."""
        transcripts, refusals = await ChannelMessageRouter()._transcribe(
            MagicMock(), _bot(provider=None, model=None), [_voice()]
        )

        assert transcripts == []
        assert len(refusals) == 1
        assert "nobody has set up a transcription provider" in refusals[0]

    async def test_a_bot_switched_off_says_so_even_where_a_provider_is_set_up(
        self, world: SimpleNamespace
    ):
        """A different reason from the one above, fixed by a different person."""
        world.org.speech_to_text_provider = "openai"
        world.org.speech_to_text_model = "whisper-1"
        transcribe = AsyncMock()

        with patch("app.services.channels.router.TranscriptionService.transcribe", transcribe):
            transcripts, refusals = await ChannelMessageRouter()._transcribe(
                MagicMock(), _bot(provider=None, model=None, transcribe=False), [_voice()]
            )

        assert transcripts == []
        assert "turned off" in refusals[0]
        transcribe.assert_not_awaited()

    async def test_a_bot_with_no_agent_bound_transcribes_nothing_and_says_nothing(
        self, world: SimpleNamespace
    ):
        """The message is refused anyway; a paid transcription first would be waste."""
        world.exposed = []
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"ogg")

        with patch("app.services.channels.router.get_adapter", return_value=adapter):
            result = await ChannelMessageRouter()._transcribe(MagicMock(), _bot(), [_voice()])

        assert result == ([], [])
        adapter.download_attachment.assert_not_awaited()

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
                AsyncMock(
                    side_effect=ExternalServiceError(
                        message="x", details={"reason": "provider_error"}
                    )
                ),
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


class TestWhichEngineAVoiceNoteReaches:
    """A bot with no pair of its own inherits, through the agent it serves."""

    async def _asked(self, bot: SimpleNamespace) -> dict[str, object]:
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"ogg")
        transcribe = AsyncMock(return_value="words")
        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch("app.services.channels.router.TranscriptionService.transcribe", transcribe),
        ):
            await ChannelMessageRouter()._transcribe(MagicMock(), bot, [_voice()])
        return transcribe.await_args.kwargs

    async def test_a_bot_with_no_pair_inherits_its_agents_override(self, world: SimpleNamespace):
        """The agent the bot's exposure serves - the only one `_transcribe` is
        ever told about. A handle somebody `@mentions` is routed after this and
        never changes which engine heard the recording."""
        world.org.speech_to_text_provider = "openai"
        world.org.speech_to_text_model = "whisper-1"
        world.spec = {
            "name": "Support",
            "speech_to_text": {"provider": "groq", "model": "whisper-large-v3", "language": "pl"},
        }

        asked = await self._asked(_bot(provider=None, model=None))

        assert (asked["provider"], asked["model"], asked["language"]) == (
            "groq",
            "whisper-large-v3",
            "pl",
        )

    async def test_a_bot_with_no_pair_and_no_agent_override_inherits_the_organizations(
        self, world: SimpleNamespace
    ):
        world.org.speech_to_text_provider = "openai"
        world.org.speech_to_text_model = "gpt-4o-transcribe"
        world.org.speech_to_text_language = "de"

        asked = await self._asked(_bot(provider=None, model=None))

        assert (asked["provider"], asked["model"], asked["language"]) == (
            "openai",
            "gpt-4o-transcribe",
            "de",
        )

    async def test_the_agents_language_reaches_a_bot_with_its_own_pair(
        self, world: SimpleNamespace
    ):
        world.spec = {"name": "Support", "speech_to_text": {"language": "pl"}}

        asked = await self._asked(_bot(provider="groq", model="whisper-large-v3-turbo"))

        assert (asked["provider"], asked["language"]) == ("groq", "pl")


def _from_slack() -> IncomingMessage:
    """A clip recorded on a phone, which Slack types `video/mp4`."""
    parsed = SlackAdapter().parse_incoming(
        {
            "event": {
                "type": "message",
                "subtype": "file_share",
                "user": "U1",
                "channel": "D1",
                "channel_type": "im",
                "ts": "1.0",
                "files": [
                    {
                        "id": "F0CLIP",
                        "name": "audio_message.mp4",
                        "mimetype": "video/mp4",
                        "filetype": "mp4",
                        "subtype": "slack_audio",
                        "media_display_type": "audio",
                        "duration_ms": 3000,
                        "size": 2048,
                        "url_private_download": "https://files.slack.com/files-pri/T1-F0CLIP/a.mp4",
                    }
                ],
            }
        },
        "bot-1",
    )
    assert parsed is not None
    return parsed


def _from_mattermost() -> IncomingMessage:
    """An `.mp3` the server stored untyped."""
    adapter = MattermostAdapter()
    adapter.remember_server("bot-1", "https://mm.test")
    post = {
        "id": "p1",
        "user_id": "u1",
        "channel_id": "c1",
        "message": "",
        "file_ids": ["f1"],
        "metadata": {
            "files": [
                {
                    "id": "f1",
                    "name": "memo.mp3",
                    "extension": "mp3",
                    "mime_type": "application/octet-stream",
                    "size": 2048,
                }
            ]
        },
    }
    parsed = adapter.parse_incoming(
        {"event": "posted", "data": {"channel_type": "D", "post": json.dumps(post)}}, "bot-1"
    )
    assert parsed is not None
    return parsed


class TestAVoiceNoteFromSlackOrMattermost:
    """From the platform's payload to the agent's prompt, on an inheriting bot."""

    @pytest.mark.parametrize(
        ("platform", "incoming", "sent_as"),
        [("slack", _from_slack, "voice.m4a"), ("mattermost", _from_mattermost, "voice.mp3")],
    )
    async def test_an_inheriting_bot_answers_from_the_transcript(
        self,
        world: SimpleNamespace,
        platform: str,
        incoming: Callable[[], IncomingMessage],
        sent_as: str,
    ):
        world.org.speech_to_text_provider = "openai"
        world.org.speech_to_text_model = "gpt-4o-transcribe"
        message = incoming()
        bot = _bot(provider=None, model=None)
        bot.platform = platform
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"audio")
        transcribe = AsyncMock(return_value="the invoice is late")

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch("app.services.channels.router.TranscriptionService.transcribe", transcribe),
        ):
            router = ChannelMessageRouter()
            recordings, rest = router._split_recordings(message)
            transcripts, refusals = await router._transcribe(MagicMock(), bot, recordings)

        assert rest == []
        assert refusals == []
        assert transcribe.await_args.args[0].filename == sent_as
        assert transcribe.await_args.kwargs["provider"] == "openai"
        assert router._with_transcripts(message.text, transcripts) == (
            "[Voice message, transcribed]\nthe invoice is late"
        )
