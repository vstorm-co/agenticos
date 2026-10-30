"""A Discord bot is reached over its Gateway connection and takes no webhook (#2079).

Every other platform's form, schema and service accept a webhook mode; Discord's
traffic arrives only over the bot's own connection, so a webhook setting on a
Discord bot would be stored, shown and never used.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from app.commands import channel as channel_commands
from app.core.exceptions import BadRequestError
from app.db.models.channel_bot import ChannelBot
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotUpdate
from app.services.channel_bot import ChannelBotService

pytestmark = pytest.mark.anyio


def _row() -> ChannelBot:
    return ChannelBot(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        platform="discord",
        name="bot",
        token_encrypted="",
        secret_key_version=1,
    )


def test_a_discord_bot_is_created_with_its_token_alone():
    created = ChannelBotCreate(platform="discord", name="bot", token="t" * 40)
    assert created.webhook_mode is False


@pytest.mark.parametrize("webhook", [{"webhook_mode": True}, {"webhook_secret": "s" * 16}])
def test_a_discord_bot_with_a_webhook_is_refused(webhook: dict[str, object]):
    with pytest.raises(ValidationError, match="takes no webhook"):
        ChannelBotCreate(platform="discord", name="bot", token="t" * 40, **webhook)


@pytest.mark.parametrize("webhook", [{"webhook_mode": True}, {"webhook_secret": "s" * 16}])
async def test_a_discord_bot_cannot_be_switched_to_a_webhook(webhook: dict[str, object]):
    bot = _row()
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org",
            new=AsyncMock(return_value=bot),
        ),
        patch("app.services.channel_bot.channel_bot_repo.update", new=AsyncMock()) as update,
        pytest.raises(BadRequestError) as refused,
    ):
        service = ChannelBotService(MagicMock(), organization_id=bot.organization_id)
        await service.update(bot.id, ChannelBotUpdate(**webhook))
    assert refused.value.details["fields"][0]["field"] == "webhook_mode"
    update.assert_not_awaited()


async def test_registering_a_webhook_for_a_discord_bot_is_refused():
    bot = _row()
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org",
            new=AsyncMock(return_value=bot),
        ),
        pytest.raises(BadRequestError, match="no webhook to register") as refused,
    ):
        await ChannelBotService(MagicMock(), organization_id=bot.organization_id).register_webhook(
            bot.id
        )
    assert refused.value.details == {"platform": "discord"}


def test_the_cli_says_a_discord_bot_has_no_webhook_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
):
    bot = _row()
    service = MagicMock(get=AsyncMock(return_value=bot))

    @asynccontextmanager
    async def scoped(org_id: str | None) -> AsyncIterator[MagicMock]:
        yield service

    monkeypatch.setattr(channel_commands, "_channel_service", scoped)
    adapter = MagicMock()
    monkeypatch.setattr(channel_commands, "get_adapter", adapter)

    result = CliRunner().invoke(
        channel_commands.channel_webhook_register, ["--bot-id", str(bot.id), "--org", "x"]
    )

    assert "has no webhook to register" in result.output
    assert result.exception is None
    adapter.assert_not_called()
