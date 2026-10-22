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
from app.services.transcription import TranscriptionResult

pytestmark = pytest.mark.anyio


def _heard(text: str, seconds: float | None = None) -> TranscriptionResult:
    return TranscriptionResult(text=text, audio_seconds=seconds)


def _voice(name: str = "voice.ogg", seconds: float | None = 3.0) -> IncomingAttachment:
    """A voice note with the length its platform reported - Telegram always says."""
    return IncomingAttachment(
        filename=name, mime_type="audio/ogg", size=2048, handle="h", duration_seconds=seconds
    )


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


_MP3_FRAME = b"\xff\xfb\x90\x00" + bytes(413)
"""One MPEG-1 Layer III frame at 128 kbit/s and 44.1 kHz: 417 bytes, 26 ms."""

_BOT_KEY = uuid4()
_ORG_KEY = uuid4()


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
        speech_to_text_secret_id=_BOT_KEY if provider else None,
    )


_SETTINGS = "app.services.speech_to_text_settings"


@pytest.fixture(autouse=True)
def usage() -> Iterator[AsyncMock]:
    """The usage rows a voice note writes, captured instead of flushed."""
    with patch("app.services.transcription_usage.record", new=AsyncMock()) as record:
        yield record


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
            speech_to_text_secret_id=_ORG_KEY,
            speech_to_text_language=None,
            dictation_max_seconds=300,
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

    def test_each_recording_is_logged_with_its_type_and_never_its_name(
        self, caplog: pytest.LogCaptureFixture
    ):
        """The line a live failure is diagnosed from: what the platform typed the
        recording, which message and which of its files - and not the name a
        sender chose, which can be personal."""
        incoming = _incoming(_voice("Call with Dr Kowalska.opus"), _document())
        incoming.message_id = "m-42"
        with caplog.at_level("INFO", logger="app.services.channels.router"):
            ChannelMessageRouter._split_recordings(incoming)

        assert "message=m-42 recording=0 type=audio/ogg" in caplog.text
        assert "Kowalska" not in caplog.text
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
            MagicMock(), _bot(provider=None, model=None), [_voice()], requested_by=None
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
                MagicMock(),
                _bot(provider=None, model=None, transcribe=False),
                [_voice()],
                requested_by=None,
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
            result = await ChannelMessageRouter()._transcribe(
                MagicMock(), _bot(), [_voice()], requested_by=None
            )

        assert result == ([], [])
        adapter.download_attachment.assert_not_awaited()

    async def test_a_message_with_no_recording_asks_nothing(self):
        transcripts, refusals = await ChannelMessageRouter()._transcribe(
            MagicMock(), _bot(), [], requested_by=None
        )

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
                AsyncMock(return_value=_heard("the second one")),
            ),
        ):
            transcripts, refusals = await ChannelMessageRouter()._transcribe(
                MagicMock(), _bot(), [_voice("a.ogg"), _voice("b.ogg")], requested_by=None
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
                MagicMock(), _bot(), [huge], requested_by=None
            )

        adapter.download_attachment.assert_not_awaited()
        assert transcripts == []
        assert "too large to transcribe" in refusals[0]

    @pytest.mark.parametrize(
        ("measured", "reported"),
        [(301.0, None), (None, 301.0)],
        ids=["read-off-the-file", "as-the-platform-reported"],
    )
    async def test_a_voice_note_longer_than_the_longest_dictation_is_never_paid_for(
        self, usage: AsyncMock, measured: float | None, reported: float | None
    ):
        """Codex on #2204: 25 MB of low-bitrate audio is hours of it, and the sender's
        limit counts messages - so the length is held to the organization's longest
        dictation before any provider is called."""
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"OggS...")
        note = IncomingAttachment(
            filename="long.ogg",
            mime_type="audio/ogg",
            size=2048,
            handle="h",
            duration_seconds=reported,
        )
        transcribe = AsyncMock(return_value=_heard("never"))

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch("app.services.channels.router.measure_audio_seconds", return_value=measured),
            patch("app.services.channels.router.TranscriptionService.transcribe", transcribe),
        ):
            transcripts, refusals = await ChannelMessageRouter()._transcribe(
                MagicMock(), _bot(), [note], requested_by=None
            )

        transcribe.assert_not_awaited()
        usage.assert_not_awaited()
        assert transcripts == []
        assert refusals == ["long.ogg: too long to transcribe (the limit is 300 seconds)."]

    async def test_a_voice_note_within_the_longest_dictation_is_transcribed(self):
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"OggS...")

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch("app.services.channels.router.measure_audio_seconds", return_value=300.0),
            patch(
                "app.services.channels.router.TranscriptionService.transcribe",
                AsyncMock(return_value=_heard("five minutes")),
            ),
        ):
            transcripts, refusals = await ChannelMessageRouter()._transcribe(
                MagicMock(), _bot(), [_voice()], requested_by=None
            )

        assert (transcripts, refusals) == (["five minutes"], [])

    async def test_a_voice_note_whose_length_nobody_can_state_is_not_paid_for(self, usage):
        """Codex on #2204: no length from the file or the platform was taken as short,
        which is exactly the file a byte cap does not bound."""
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"not a container")
        transcribe = AsyncMock(return_value=_heard("never"))

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch("app.services.channels.router.TranscriptionService.transcribe", transcribe),
        ):
            transcripts, refusals = await ChannelMessageRouter()._transcribe(
                MagicMock(), _bot(), [_voice("memo.ogg", seconds=None)], requested_by=None
            )

        transcribe.assert_not_awaited()
        usage.assert_not_awaited()
        assert refusals == ["memo.ogg: its length could not be read, so it was not transcribed."]

    async def test_a_recording_at_the_limit_is_still_fetched(self):
        """The cap is a ceiling, not a margin."""
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"ogg")
        edge = IncomingAttachment(
            filename="edge.ogg",
            mime_type="audio/ogg",
            size=TRANSCRIPTION_MAX_BYTES,
            handle="h",
            duration_seconds=60.0,
        )

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch(
                "app.services.channels.router.TranscriptionService.transcribe",
                AsyncMock(return_value=_heard("just fits")),
            ),
        ):
            transcripts, _ = await ChannelMessageRouter()._transcribe(
                MagicMock(), _bot(), [edge], requested_by=None
            )

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
                MagicMock(), _bot(), [_voice()], requested_by=None
            )

        assert transcripts == []
        assert refusals == ["voice.ogg: could not be transcribed."]

    async def test_the_configured_model_is_the_one_asked(self):
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"ogg")
        transcribe = AsyncMock(return_value=_heard("words"))
        bot = _bot(provider="groq", model="whisper-large-v3-turbo")

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch("app.services.channels.router.TranscriptionService.transcribe", transcribe),
        ):
            await ChannelMessageRouter()._transcribe(
                MagicMock(), bot, [_voice()], requested_by=None
            )

        assert transcribe.await_args.kwargs["provider"] == "groq"
        assert transcribe.await_args.kwargs["model"] == "whisper-large-v3-turbo"
        assert transcribe.await_args.kwargs["organization_id"] == bot.organization_id
        # The bot's own key, which is spent for everybody who writes to it.
        sent = transcribe.await_args.kwargs
        assert (sent["secret_id"], sent["shared_key"]) == (_BOT_KEY, True)


class TestTheUsageRowAVoiceNoteLeaves:
    """Every recording handed to the provider is recorded against the bot (#1797)."""

    async def _send(
        self,
        world: SimpleNamespace,
        recording: IncomingAttachment,
        transcribe: AsyncMock,
        *,
        requested_by: object = None,
        content: bytes = b"ogg-bytes",
    ) -> tuple[SimpleNamespace, list[str], list[str]]:
        bot = _bot(provider="groq", model="whisper-large-v3-turbo")
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=content)
        db = MagicMock()
        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch("app.services.channels.router.TranscriptionService.transcribe", transcribe),
        ):
            transcripts, refusals = await ChannelMessageRouter()._transcribe(
                db, bot, [recording], requested_by=requested_by
            )
        return bot, transcripts, refusals

    async def test_a_heard_note_is_recorded_with_its_bot_agent_and_linked_person(
        self, world: SimpleNamespace, usage: AsyncMock
    ):
        person = uuid4()
        bot, transcripts, _ = await self._send(
            world, _voice(), AsyncMock(return_value=_heard("hi", 2.5)), requested_by=person
        )

        assert transcripts == ["hi"]
        call = usage.await_args.args[1]
        agent = world.exposed[0][1]
        assert (call.surface, call.channel_bot_id, call.agent_id) == ("channel", bot.id, agent.id)
        assert call.requested_by_user_id == person
        assert call.organization_id == bot.organization_id
        assert (call.provider, call.model) == ("groq", "whisper-large-v3-turbo")
        assert call.secret_id == _BOT_KEY
        kwargs = usage.await_args.kwargs
        assert kwargs["audio_seconds"] == 2.5
        assert kwargs["input_bytes"] == len(b"ogg-bytes")
        assert "failure" not in kwargs

    async def test_the_platforms_length_stands_in_where_the_provider_gives_none(
        self, world: SimpleNamespace, usage: AsyncMock
    ):
        """Telegram and Slack state a voice note's length; `gpt-4o-transcribe` does not."""
        timed = IncomingAttachment(
            filename="voice.ogg", mime_type="audio/ogg", size=2048, handle="h", duration_seconds=7
        )
        await self._send(world, timed, AsyncMock(return_value=_heard("hi")))

        assert usage.await_args.kwargs["audio_seconds"] == 7

    async def test_the_providers_length_wins_over_the_platforms(
        self, world: SimpleNamespace, usage: AsyncMock
    ):
        timed = IncomingAttachment(
            filename="voice.ogg", mime_type="audio/ogg", size=2048, handle="h", duration_seconds=7
        )
        await self._send(world, timed, AsyncMock(return_value=_heard("hi", 6.8)))

        assert usage.await_args.kwargs["audio_seconds"] == 6.8

    async def test_a_failed_note_is_recorded_as_failed_with_the_platforms_length(
        self, world: SimpleNamespace, usage: AsyncMock
    ):
        failure = ExternalServiceError(message="x", details={"reason": "timeout"})
        timed = IncomingAttachment(
            filename="voice.ogg", mime_type="audio/ogg", size=2048, handle="h", duration_seconds=4
        )
        _, transcripts, refusals = await self._send(
            world, timed, AsyncMock(side_effect=failure), requested_by=None
        )

        assert (transcripts, refusals) == ([], ["voice.ogg: could not be transcribed."])
        assert usage.await_args.kwargs["failure"] is failure
        assert usage.await_args.kwargs["audio_seconds"] == 4
        assert usage.await_args.args[1].requested_by_user_id is None

    @pytest.mark.parametrize(
        "transcribe",
        [
            AsyncMock(return_value=_heard("hi")),
            AsyncMock(side_effect=ExternalServiceError(message="x", details={})),
        ],
        ids=["heard", "failed"],
    )
    async def test_the_length_read_off_the_file_is_what_is_recorded(
        self, world: SimpleNamespace, usage: AsyncMock, transcribe: AsyncMock
    ):
        """A Mattermost note states no length and the provider may not either: the
        figure that let it through the limit is the one its usage carries."""
        untimed = _voice("voice.mp3", seconds=None)
        await self._send(world, untimed, transcribe, content=_MP3_FRAME * 10)

        assert usage.await_args.kwargs["audio_seconds"] == pytest.approx(10 * 1152 / 44_100)

    async def test_nothing_is_recorded_when_nothing_was_attempted(
        self, world: SimpleNamespace, usage: AsyncMock
    ):
        """Off, nothing resolving, too large or not downloaded: no provider was asked."""
        await ChannelMessageRouter()._transcribe(
            MagicMock(), _bot(transcribe=False), [_voice()], requested_by=None
        )
        await ChannelMessageRouter()._transcribe(
            MagicMock(), _bot(provider=None, model=None), [_voice()], requested_by=None
        )
        huge = IncomingAttachment(
            filename="huge.ogg",
            mime_type="audio/ogg",
            size=TRANSCRIPTION_MAX_BYTES + 1,
            handle="h",
        )
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(side_effect=RuntimeError("gone"))
        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
        ):
            await ChannelMessageRouter()._transcribe(
                MagicMock(), _bot(), [huge, _voice()], requested_by=None
            )

        usage.assert_not_awaited()


class TestWhichEngineAVoiceNoteReaches:
    """A bot with no pair of its own inherits, through the agent it serves."""

    async def _asked(self, bot: SimpleNamespace) -> dict[str, object]:
        adapter = MagicMock()
        adapter.download_attachment = AsyncMock(return_value=b"ogg")
        transcribe = AsyncMock(return_value=_heard("words"))
        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch("app.services.channels.router.TranscriptionService.transcribe", transcribe),
        ):
            await ChannelMessageRouter()._transcribe(
                MagicMock(), bot, [_voice()], requested_by=None
            )
        return transcribe.await_args.kwargs

    async def test_a_bot_with_no_pair_inherits_its_agents_override(self, world: SimpleNamespace):
        """The agent the bot's exposure serves - the only one `_transcribe` is
        ever told about. A handle somebody `@mentions` is routed after this and
        never changes which engine heard the recording."""
        world.org.speech_to_text_provider = "openai"
        world.org.speech_to_text_model = "whisper-1"
        agent_key = uuid4()
        world.spec = {
            "name": "Support",
            "speech_to_text": {
                "provider": "groq",
                "model": "whisper-large-v3",
                "language": "pl",
                "secret_id": str(agent_key),
            },
        }

        asked = await self._asked(_bot(provider=None, model=None))

        assert (asked["provider"], asked["model"], asked["language"]) == (
            "groq",
            "whisper-large-v3",
            "pl",
        )
        # The agent's key comes with the agent's pair, lent by its publisher.
        assert (asked["secret_id"], asked["shared_key"]) == (agent_key, False)

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
        assert (asked["secret_id"], asked["shared_key"]) == (_ORG_KEY, True)

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
        # One real MP3 frame (MPEG-1 Layer III, 128 kbit/s): Mattermost states no
        # length, so the router reads it off the file.
        adapter.download_attachment = AsyncMock(return_value=_MP3_FRAME)
        transcribe = AsyncMock(return_value=_heard("the invoice is late"))

        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="tok"),
            patch("app.services.channels.router.TranscriptionService.transcribe", transcribe),
        ):
            router = ChannelMessageRouter()
            recordings, rest = router._split_recordings(message)
            transcripts, refusals = await router._transcribe(
                MagicMock(), bot, recordings, requested_by=None
            )

        assert rest == []
        assert refusals == []
        assert transcribe.await_args.args[0].filename == sent_as
        assert transcribe.await_args.kwargs["provider"] == "openai"
        assert router._with_transcripts(message.text, transcripts) == (
            "[Voice message, transcribed]\nthe invoice is late"
        )
