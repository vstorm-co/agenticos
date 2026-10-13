"""A bot's own transcription switch, and the pair it may or may not carry (#1797).

The pair used to mean two things: which engine, and - when null - "off". Now
the agent and the organization can name an engine too, so a null pair inherits
and "off" is `transcribe_voice_notes`. What is held here is that the two cannot
disagree: an off bot never carries a pair, a null for the switch is refused
rather than dropped, and a bot registered by a client that never heard of the
switch inherits.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError
from app.db.models.channel_bot import ChannelBot
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotRead, ChannelBotUpdate
from app.services.channel_bot import ChannelBotService
from app.services.speech_to_text_settings import BotSpeechToText, ResolvedSpeechToText

pytestmark = pytest.mark.anyio


def _row(
    *,
    transcribe: bool = True,
    provider: str | None = None,
    model: str | None = None,
) -> ChannelBot:
    return ChannelBot(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        platform="telegram",
        name="bot",
        token_encrypted="",
        secret_key_version=1,
        transcribe_voice_notes=transcribe,
        speech_to_text_provider=provider,
        speech_to_text_model=model,
    )


async def _created(**fields: object) -> dict:
    """The keyword arguments `create` hands the repository."""
    data = ChannelBotCreate(platform="telegram", name="bot", token="t" * 20, **fields)
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.create",
            new=AsyncMock(return_value=MagicMock()),
        ) as repo_create,
        patch("app.services.channel_bot.spawn_after_commit"),
    ):
        await ChannelBotService(MagicMock(), organization_id=uuid.uuid4()).create(data)
    return repo_create.call_args.kwargs


async def _updated(bot: ChannelBot, data: ChannelBotUpdate) -> dict:
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org",
            new=AsyncMock(return_value=bot),
        ),
        patch(
            "app.services.channel_bot.channel_bot_repo.update",
            new=AsyncMock(return_value=bot),
        ) as repo_update,
        patch("app.services.channel_bot.spawn_after_commit"),
    ):
        service = ChannelBotService(MagicMock(), organization_id=bot.organization_id)
        await service.update(bot.id, data)
    return repo_update.call_args.kwargs["update_data"]


class TestCreating:
    async def test_a_bot_that_names_nothing_inherits(self):
        """The CLI and older API clients send neither field, and get "inherit" -
        which costs nothing until the agent or the organization names a provider."""
        created = await _created()

        assert created["transcribe_voice_notes"] is True
        assert created["speech_to_text_provider"] is None

    async def test_a_bot_created_off_drops_any_pair_it_was_sent(self):
        created = await _created(
            transcribe_voice_notes=False,
            speech_to_text_provider="openai",
            speech_to_text_model="whisper-1",
        )

        assert created["transcribe_voice_notes"] is False
        assert created["speech_to_text_provider"] is None
        assert created["speech_to_text_model"] is None

    async def test_a_bot_created_with_its_own_pair_keeps_it(self):
        created = await _created(
            speech_to_text_provider="groq", speech_to_text_model="whisper-large-v3"
        )

        assert (created["speech_to_text_provider"], created["speech_to_text_model"]) == (
            "groq",
            "whisper-large-v3",
        )


class TestUpdating:
    async def test_switching_off_clears_the_pair(self):
        """An off bot carrying an engine reads as configured and does nothing."""
        bot = _row(provider="openai", model="whisper-1")

        changes = await _updated(bot, ChannelBotUpdate(transcribe_voice_notes=False))

        assert changes == {
            "transcribe_voice_notes": False,
            "speech_to_text_provider": None,
            "speech_to_text_model": None,
        }

    async def test_switching_off_wins_over_a_pair_sent_with_it(self):
        bot = _row()

        changes = await _updated(
            bot,
            ChannelBotUpdate(
                transcribe_voice_notes=False,
                speech_to_text_provider="openai",
                speech_to_text_model="whisper-1",
            ),
        )

        assert changes["speech_to_text_provider"] is None

    async def test_clearing_the_pair_now_means_inherit(self):
        """The meaning change the API documents: a null pair keeps the bot on."""
        bot = _row(provider="openai", model="whisper-1")

        changes = await _updated(
            bot, ChannelBotUpdate(speech_to_text_provider=None, speech_to_text_model=None)
        )

        assert changes == {"speech_to_text_provider": None, "speech_to_text_model": None}

    async def test_turning_on_with_a_pair_stores_both(self):
        bot = _row(transcribe=False)

        changes = await _updated(
            bot,
            ChannelBotUpdate(
                transcribe_voice_notes=True,
                speech_to_text_provider="openai",
                speech_to_text_model="whisper-1",
            ),
        )

        assert changes["transcribe_voice_notes"] is True
        assert changes["speech_to_text_model"] == "whisper-1"

    async def test_a_pair_for_a_bot_that_stays_off_is_refused(self):
        bot = _row(transcribe=False)

        with pytest.raises(BadRequestError) as refused:
            await _updated(
                bot,
                ChannelBotUpdate(
                    speech_to_text_provider="openai", speech_to_text_model="whisper-1"
                ),
            )

        assert refused.value.details["fields"][0]["field"] == "transcribe_voice_notes"

    async def test_an_explicit_null_for_the_switch_is_refused(self):
        """Dropped, it would be a silent no-op for a client that meant the old
        "null is off" - and its bot would go on transcribing."""
        bot = _row()

        with pytest.raises(BadRequestError) as refused:
            await _updated(bot, ChannelBotUpdate(transcribe_voice_notes=None))

        assert refused.value.details["fields"][0]["field"] == "transcribe_voice_notes"

    async def test_a_half_pair_against_the_stored_row_is_still_refused(self):
        bot = _row()

        with pytest.raises(BadRequestError):
            await _updated(bot, ChannelBotUpdate(speech_to_text_provider="openai"))


def _readable(bot: ChannelBot) -> None:
    """The columns an insert would have defaulted, so the row validates as a read."""
    bot.access_policy = {}
    bot.is_active = True
    bot.webhook_mode = False
    bot.created_at = datetime.now(UTC)


class TestWhatInheritingWouldGive:
    """The single-bot read carries what "Inherit" resolves to, for its hint."""

    async def _read(self, bot: ChannelBot, settings: BotSpeechToText) -> ChannelBotRead:
        with (
            patch(
                "app.services.channel_bot.channel_bot_repo.get_for_org",
                new=AsyncMock(return_value=bot),
            ),
            patch(
                "app.services.channel_bot.SpeechToTextSettingsService.for_bot",
                new=AsyncMock(return_value=settings),
            ) as for_bot,
        ):
            read = await ChannelBotService(MagicMock(), organization_id=bot.organization_id).read(
                bot.id
            )
        assert for_bot.await_args.kwargs == {"inherited": True}
        return read

    async def test_it_names_the_agent_the_pair_came_from(self):
        bot = _row(provider="openai", model="whisper-1")
        _readable(bot)
        resolved = ResolvedSpeechToText(
            provider="groq",
            model="whisper-large-v3",
            language="pl",
            pair_source="agent",
            language_source="agent",
        )

        read = await self._read(
            bot, BotSpeechToText(exposed=True, agent_name="Support", resolved=resolved)
        )

        assert read.inherited_speech_to_text is not None
        assert read.inherited_speech_to_text.model_dump() == {
            "provider": "groq",
            "model": "whisper-large-v3",
            "language": "pl",
            "pair_source": "agent",
            "language_source": "agent",
            "agent_name": "Support",
        }
        # The bot's own pair is still what it is set to.
        assert read.speech_to_text_provider == "openai"

    async def test_nothing_to_inherit_reads_as_null(self):
        bot = _row()
        _readable(bot)

        read = await self._read(bot, BotSpeechToText(exposed=False, agent_name=None, resolved=None))

        assert read.inherited_speech_to_text is None
