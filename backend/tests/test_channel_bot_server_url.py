"""A self-hosted bot carries its own server's address (#24, #41).

`ChannelBot.api_base_url` was on the model and read by the startup poller and the
router, and was a field on no schema, no repository function, no CLI command and
no form. There was no way to write it short of an `UPDATE`, so every Mattermost
bot ever created had `api_base_url IS NULL` - permanently, and by construction:
the event stream logged "no server URL; cannot open a stream" and returned,
`send_message` raised, and an attachment could not be fetched.

`tests/test_mattermost_channel.py` asserted that loud failure all along. It was
asserting the state every bot was in.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.core.vault import VaultScope, unseal
from app.db.models.channel_bot import ChannelBot
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotRead, ChannelBotUpdate
from app.services.channel_bot import ChannelBotService

pytestmark = pytest.mark.anyio

SERVER = "https://mattermost.acme.internal"


def _mattermost(**overrides) -> dict:
    return {
        "platform": "mattermost",
        "name": "bot",
        "token": "t" * 20,
        "api_base_url": SERVER,
        **overrides,
    }


def _row(platform: str = "mattermost") -> ChannelBot:
    return ChannelBot(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        platform=platform,
        name="bot",
        token_encrypted="",
        secret_key_version=1,
    )


async def _created(data: ChannelBotCreate) -> dict:
    """The keyword arguments `create` hands the repository."""
    with patch(
        "app.services.channel_bot.channel_bot_repo.create",
        new=AsyncMock(return_value=MagicMock()),
    ) as repo_create:
        await ChannelBotService(MagicMock(), organization_id=uuid.uuid4()).create(data)
    return repo_create.call_args.kwargs


async def _updated(bot: ChannelBot, **fields: object) -> dict:
    with (
        patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org",
            new=AsyncMock(return_value=bot),
        ),
        patch(
            "app.services.channel_bot.channel_bot_repo.update",
            new=AsyncMock(return_value=bot),
        ) as repo_update,
    ):
        service = ChannelBotService(MagicMock(), organization_id=bot.organization_id)
        await service.update(bot.id, ChannelBotUpdate(**fields))
    return repo_update.call_args.kwargs["update_data"]


class TestCreating:
    async def test_the_server_url_reaches_the_row(self):
        assert (await _created(ChannelBotCreate(**_mattermost())))["api_base_url"] == SERVER

    async def test_a_mattermost_bot_without_a_server_url_is_refused(self):
        """The adapter's docstring has always promised this is reported when the
        bot is saved rather than the first time somebody messages it. Until now
        it promised a check that did not exist."""
        with pytest.raises(ValidationError, match="needs its server's URL"):
            ChannelBotCreate(**_mattermost(api_base_url=None))

    async def test_another_platform_may_not_carry_one(self):
        """Telegram and Slack have one address for everybody, so a server URL
        there is a value nothing will ever read."""
        with pytest.raises(ValidationError, match="one address for everybody"):
            ChannelBotCreate(platform="telegram", name="bot", token="t" * 20, api_base_url=SERVER)


class TestWhatCountsAsAnAddress:
    """Scheme and shape, not reachability - the deliberate answer to #41's
    acceptance criteria, which asked for `validate_webhook_url`. That one
    resolves DNS to prove a host is public, and a Mattermost server behind a VPN
    is the deployment this feature exists for."""

    @pytest.mark.parametrize(
        "address",
        [
            "https://mattermost.acme.internal",
            "http://mattermost:8065",
            "http://10.0.0.7:8065",
            "http://localhost:8065",
        ],
    )
    async def test_a_private_address_is_accepted(self, address: str):
        ChannelBotCreate(**_mattermost(api_base_url=address))

    @pytest.mark.parametrize(
        "address",
        [
            "ftp://mattermost.acme.internal",
            "file:///etc/passwd",
            "https://",
            "http://user:pass@mattermost.acme.internal",
            "http://169.254.169.254",
            "http://metadata.google.internal",
        ],
    )
    async def test_what_is_never_a_mattermost_server_is_refused(self, address: str):
        with pytest.raises(ValidationError):
            ChannelBotCreate(**_mattermost(api_base_url=address))


class TestUpdating:
    async def test_the_server_url_can_be_changed(self):
        update_data = await _updated(_row(), api_base_url="https://mattermost.new.internal")
        assert update_data["api_base_url"] == "https://mattermost.new.internal"

    async def test_a_mattermost_bot_cannot_lose_its_server_url(self):
        """The case the create-time schema rule cannot express: clearing it
        returns the bot to the state every Mattermost bot used to be in."""
        with pytest.raises(BadRequestError, match="cannot lose its server URL"):
            await _updated(_row(), api_base_url=None)

    async def test_another_platform_cannot_gain_one(self):
        with pytest.raises(BadRequestError, match="one address for everybody"):
            await _updated(_row("telegram"), api_base_url=SERVER)


class TestThePastedSecret:
    """Mattermost mints the token when the outgoing webhook is created, and the
    operator pastes it here. Generating one locally is what made this path
    unusable: the bot compared Mattermost's token against a random string nobody
    could overwrite."""

    async def test_a_pasted_secret_is_sealed_rather_than_stored(self):
        kwargs = await _created(
            ChannelBotCreate(**_mattermost(webhook_mode=True, webhook_secret="from-mattermost"))
        )
        sealed = kwargs["webhook_secret_encrypted"]
        assert "from-mattermost" not in sealed
        assert (
            unseal(sealed, scope=VaultScope.organization(kwargs["organization_id"]))
            == "from-mattermost"
        )

    async def test_a_mattermost_bot_in_webhook_mode_mints_nothing(self):
        kwargs = await _created(ChannelBotCreate(**_mattermost(webhook_mode=True)))
        assert kwargs["webhook_secret_encrypted"] is None

    async def test_a_telegram_bot_still_gets_one_minted(self):
        """`setWebhook` takes the secret as a parameter, so there the deployment
        is the side that hands it over."""
        kwargs = await _created(
            ChannelBotCreate(platform="telegram", name="bot", token="t" * 20, webhook_mode=True)
        )
        assert kwargs["webhook_secret_encrypted"] is not None

    async def test_the_secret_is_never_in_a_response_schema(self):
        """`ChannelBotRead` answers whether one is configured, never with it."""
        assert "webhook_secret" not in ChannelBotRead.model_fields
        assert "has_webhook_secret" in ChannelBotRead.model_fields
