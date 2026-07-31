"""Tests for organization scoping of channel bots.

A bot belongs to one organization, and every conversation it opens inherits that
organization - which is what allows `conversations.organization_id` to be
NOT NULL despite channel conversations having no user.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.vault import VaultScope, unseal
from app.db.models.channel_bot import ChannelBot
from app.schemas.channel_bot import AccessPolicy, ChannelBotCreate, ChannelBotUpdate
from app.services.channel_bot import ChannelBotService, unseal_bot_token


def _bot(organization_id=None, is_active: bool = True):
    bot = MagicMock()
    bot.id = uuid.uuid4()
    bot.organization_id = organization_id or uuid.uuid4()
    bot.is_active = is_active
    return bot


class TestChannelBotServiceScope:
    """Management calls act on the caller's organization only."""

    @pytest.mark.anyio
    async def test_get_passes_org_to_repo(self):
        org_id = uuid.uuid4()
        bot = _bot(org_id)

        with patch(
            "app.services.channel_bot.channel_bot_repo.get_for_org",
            new=AsyncMock(return_value=bot),
        ) as repo_get:
            service = ChannelBotService(MagicMock(), organization_id=org_id)
            result = await service.get(bot.id)

        assert result is bot
        assert repo_get.call_args.kwargs["organization_id"] == org_id

    @pytest.mark.anyio
    async def test_foreign_bot_reads_as_missing(self):
        """Another org's bot is 404, not 403 - the id must not be probeable."""
        with (
            patch(
                "app.services.channel_bot.channel_bot_repo.get_for_org",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError),
        ):
            service = ChannelBotService(MagicMock(), organization_id=uuid.uuid4())
            await service.get(uuid.uuid4())

    @pytest.mark.anyio
    async def test_create_stamps_org(self):
        org_id = uuid.uuid4()
        data = ChannelBotCreate(
            platform="telegram",
            name="Support",
            token="secret-token",
            access_policy=AccessPolicy(),
        )

        with patch(
            "app.services.channel_bot.channel_bot_repo.create",
            new=AsyncMock(return_value=_bot(org_id)),
        ) as repo_create:
            service = ChannelBotService(MagicMock(), organization_id=org_id)
            await service.create(data)

        stored = repo_create.call_args.kwargs
        assert stored["organization_id"] == org_id
        # Sealed for this organization, not with a deployment-wide key: the
        # token is what talks to Telegram *as* this tenant.
        assert "secret-token" not in stored["token_encrypted"]
        assert (
            unseal(
                stored["token_encrypted"],
                scope=VaultScope.organization(org_id),
                key_version=stored["secret_key_version"],
            )
            == "secret-token"
        )

    @pytest.mark.anyio
    async def test_a_bot_token_cannot_be_read_by_another_organization(self):
        """The property a single global Fernet key could not give.

        Before this, a ciphertext copied from one tenant's row into another's
        decrypted happily, and the token is what posts to Slack as that
        organization.
        """
        org_id = uuid.uuid4()
        data = ChannelBotCreate(
            platform="slack",
            name="Support",
            token="xoxb-secret",
            access_policy=AccessPolicy(),
        )

        with patch(
            "app.services.channel_bot.channel_bot_repo.create",
            new=AsyncMock(return_value=_bot(org_id)),
        ) as repo_create:
            await ChannelBotService(MagicMock(), organization_id=org_id).create(data)

        stolen = _bot(uuid.uuid4())
        stolen.token_encrypted = repo_create.call_args.kwargs["token_encrypted"]
        stolen.secret_key_version = repo_create.call_args.kwargs["secret_key_version"]

        with pytest.raises(BadRequestError, match="Failed to decrypt"):
            unseal_bot_token(stolen)

    @pytest.mark.anyio
    async def test_list_all_scoped_to_org(self):
        org_id = uuid.uuid4()

        with (
            patch(
                "app.services.channel_bot.channel_bot_repo.list_for_org",
                new=AsyncMock(return_value=[]),
            ) as repo_list,
            patch(
                "app.services.channel_bot.channel_bot_repo.count",
                new=AsyncMock(return_value=0),
            ) as repo_count,
        ):
            service = ChannelBotService(MagicMock(), organization_id=org_id)
            await service.list_all()

        assert repo_list.call_args.kwargs["organization_id"] == org_id
        assert repo_count.call_args.kwargs["organization_id"] == org_id

    @pytest.mark.anyio
    async def test_unscoped_service_refuses_management(self):
        """The inbound-only service must not be usable to list another tenant's bots."""
        service = ChannelBotService(MagicMock())

        with pytest.raises(RuntimeError, match="without an organization"):
            await service.list_all()

    @pytest.mark.anyio
    async def test_unscoped_service_still_dispatches_inbound(self):
        """find_active is the inbound path and needs no organization."""
        bot = _bot()

        with patch(
            "app.services.channel_bot.channel_bot_repo.get_for_inbound",
            new=AsyncMock(return_value=bot),
        ):
            service = ChannelBotService(MagicMock())
            result = await service.find_active(bot.id)

        assert result is bot

    @pytest.mark.anyio
    async def test_inactive_bot_is_not_dispatched(self):
        with patch(
            "app.services.channel_bot.channel_bot_repo.get_for_inbound",
            new=AsyncMock(return_value=_bot(is_active=False)),
        ):
            service = ChannelBotService(MagicMock())
            assert await service.find_active(uuid.uuid4()) is None


class TestSlackAppCredentials:
    """Each Slack bot is its own Slack app - the credentials live on the row.

    Sealed like the token and never returned; what a response may carry is the
    boolean pair, which `tests/api/test_no_secret_escapes.py` polices.
    """

    @pytest.mark.anyio
    async def test_slack_credentials_are_sealed_not_stored_bare(self):
        org_id = uuid.uuid4()
        data = ChannelBotCreate(
            platform="slack",
            name="Acme Support",
            token="xoxb-bot-token",
            slack_signing_secret="shhh-signing",
            slack_app_token="xapp-1-token",
        )

        with patch(
            "app.services.channel_bot.channel_bot_repo.create",
            new=AsyncMock(return_value=_bot(org_id)),
        ) as repo_create:
            await ChannelBotService(MagicMock(), organization_id=org_id).create(data)

        stored = repo_create.call_args.kwargs
        assert "shhh-signing" not in stored["slack_signing_secret_encrypted"]
        assert "xapp-1-token" not in stored["slack_app_token_encrypted"]
        scope = VaultScope.organization(org_id)
        version = stored["secret_key_version"]
        assert (
            unseal(stored["slack_signing_secret_encrypted"], scope=scope, key_version=version)
            == "shhh-signing"
        )
        assert (
            unseal(stored["slack_app_token_encrypted"], scope=scope, key_version=version)
            == "xapp-1-token"
        )

    @pytest.mark.anyio
    async def test_slack_credentials_on_another_platform_are_refused(self):
        """Accepting them would store secrets nothing will ever read."""
        data = ChannelBotCreate(
            platform="telegram",
            name="TG",
            token="123456:telegram-token",
            slack_signing_secret="shhh-signing",
        )

        with pytest.raises(BadRequestError, match="Slack"):
            await ChannelBotService(MagicMock(), organization_id=uuid.uuid4()).create(data)

    @pytest.mark.anyio
    async def test_an_explicit_null_clears_a_stored_credential(self):
        """Omission leaves it, null removes it - two different requests."""
        org_id = uuid.uuid4()
        bot = _bot(org_id)
        bot.platform = "slack"
        bot.secret_key_version = 1
        service = ChannelBotService(MagicMock(), organization_id=org_id)

        with (
            patch.object(service, "get", new=AsyncMock(return_value=bot)),
            patch(
                "app.services.channel_bot.channel_bot_repo.update",
                new=AsyncMock(return_value=bot),
            ) as repo_update,
        ):
            await service.update(bot.id, ChannelBotUpdate.model_validate({"slack_app_token": None}))

        assert repo_update.call_args.kwargs["update_data"] == {"slack_app_token_encrypted": None}

    def test_the_booleans_say_configured_and_never_the_value(self):
        configured = ChannelBot(slack_signing_secret_encrypted="enc:x")
        bare = ChannelBot()

        assert configured.has_slack_signing_secret is True
        assert (bare.has_slack_signing_secret, bare.has_slack_app_token) == (False, False)


class TestChannelConversationOrg:
    """A channel conversation inherits the bot's organization, not a user's."""

    @pytest.mark.anyio
    async def test_new_session_conversation_uses_bot_org(self):
        from app.services.channels.base import IncomingMessage
        from app.services.channels.router import ChannelMessageRouter

        bot = _bot()
        identity = MagicMock(id=uuid.uuid4(), user_id=uuid.uuid4())
        incoming = IncomingMessage(
            platform="slack",
            bot_id=str(bot.id),
            platform_user_id="U123",
            platform_chat_id="C123",
            chat_type="channel",
            text="hi",
        )

        with (
            patch(
                "app.services.channels.router.channel_session_repo.get_by_bot_and_chat",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.channels.router.conversation_repo.create_conversation",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ) as create_conv,
            patch(
                "app.services.channels.router.channel_session_repo.create",
                new=AsyncMock(return_value=MagicMock()),
            ),
        ):
            await ChannelMessageRouter()._resolve_session(incoming, bot, identity, MagicMock())

        assert create_conv.call_args.kwargs["organization_id"] == bot.organization_id
