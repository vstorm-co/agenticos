"""Tests for organization scoping of channel bots.

A bot belongs to one organization, and every conversation it opens inherits that
organization - which is what allows `conversations.organization_id` to be
NOT NULL despite channel conversations having no user.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
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
            # Resolving a session also records that the chat had a turn, which is
            # what "report usage every n messages" counts.
            patch(
                "app.services.channels.router.channel_session_repo.touch",
                new=AsyncMock(return_value=MagicMock()),
            ),
        ):
            await ChannelMessageRouter()._resolve_session(incoming, bot, identity, MagicMock())

        assert create_conv.call_args.kwargs["organization_id"] == bot.organization_id


class TestWhoAnswersOnEachBot:
    """The channels listing says which agents a bot serves, and when none does.

    "Registered and silent" is the state somebody opens that page to explain,
    and from a chat window it is indistinguishable from a broken bot. Resolved
    with the listing rather than fetched per row by the client: an organization
    with a dozen channels would otherwise be a dozen requests behind one table.
    """

    @staticmethod
    def _row(**overrides) -> SimpleNamespace:
        """A bot row real enough for `ChannelBotRead` to validate.

        `_bot` above is a bare `MagicMock`, which is all the scoping tests need
        - they assert on what a repository was asked. This listing builds a
        schema out of the row, so every column has to be the type it is.
        """
        return SimpleNamespace(
            id=uuid.uuid4(),
            platform="mattermost",
            name="Acme Support",
            is_active=True,
            webhook_mode=False,
            webhook_url=None,
            api_base_url="https://mattermost.acme.com",
            access_policy={},
            usage_reporting={},
            has_webhook_secret=False,
            has_slack_signing_secret=False,
            has_slack_app_token=False,
            created_at=datetime.now(UTC),
            updated_at=None,
            **overrides,
        )

    @staticmethod
    def _agent(slug: str = "support") -> MagicMock:
        agent = MagicMock(id=uuid.uuid4(), slug=slug, has_avatar=False)
        agent.name = slug.title()
        return agent

    async def _listed(self, *, bots: list, answering: dict) -> list:
        with (
            patch(
                "app.services.channel_bot.channel_bot_repo.list_for_org",
                new=AsyncMock(return_value=bots),
            ),
            patch(
                "app.services.channel_bot.channel_bot_repo.count",
                new=AsyncMock(return_value=len(bots)),
            ),
            patch(
                "app.services.channel_bot.agent_exposure_repo.active_agents_for_bots",
                new=AsyncMock(return_value=answering),
            ) as grouped,
        ):
            rows, _total = await ChannelBotService(
                MagicMock(), organization_id=uuid.uuid4()
            ).list_all()
        self.asked_for = grouped.call_args.kwargs["channel_bot_ids"]
        return rows

    @pytest.mark.anyio
    async def test_a_bot_names_the_agents_that_answer_on_it(self):
        bot = self._row()
        agent = self._agent()

        (row,) = await self._listed(bots=[bot], answering={bot.id: [agent]})

        assert [(found.slug, found.name) for found in row.agents] == [("support", "Support")]

    @pytest.mark.anyio
    async def test_a_bot_nobody_bound_says_so_with_an_empty_list(self):
        bot = self._row()

        (row,) = await self._listed(bots=[bot], answering={})

        assert row.agents == []

    @pytest.mark.anyio
    async def test_every_bot_on_the_page_is_asked_about_at_once(self):
        """One grouped query, not one per row."""
        bots = [self._row() for _ in range(3)]

        await self._listed(bots=bots, answering={})

        assert self.asked_for == [bot.id for bot in bots]

    @pytest.mark.anyio
    async def test_an_empty_page_asks_about_nothing(self):
        await self._listed(bots=[], answering={})

        assert self.asked_for == []


class TestAStreamThatOpensWithoutARestart:
    """A polling bot is reached over a connection this process holds.

    Only the lifespan ever opened one, so registering a bot wrote a row and
    produced silence until somebody restarted the API - and pausing had the
    mirror problem with the worse shape: a bot switched off went on answering.
    """

    @staticmethod
    def _bot_row(**overrides) -> MagicMock:
        bot = MagicMock(
            id=uuid.uuid4(),
            platform="mattermost",
            webhook_mode=False,
            is_active=True,
            api_base_url="https://mattermost.acme.com",
            slack_app_token_encrypted=None,
        )
        bot.name = "Acme Support"
        for key, value in overrides.items():
            setattr(bot, key, value)
        return bot

    def _deferred(self, bot: MagicMock) -> list[str]:
        """The names of the background tasks a write queued behind its commit."""
        service = ChannelBotService(MagicMock(), organization_id=uuid.uuid4())
        queued: list[str] = []
        with (
            patch(
                "app.services.channel_bot.spawn_after_commit",
                side_effect=lambda _db, coro, *, name: (coro.close(), queued.append(name))[1],
            ),
            patch("app.services.channel_bot.unseal_bot_token", return_value="tok"),
            patch("app.services.channel_bot.unseal_slack_app_token", return_value=None),
        ):
            service._reopen_stream(bot)
        return queued

    def test_a_live_polling_bot_gets_its_stream_opened(self):
        (name,) = self._deferred(self._bot_row())

        assert name.startswith("open_channel_stream:")

    def test_a_paused_bot_gets_its_stream_closed(self):
        """The one that needed a deploy: switched off and still answering."""
        (name,) = self._deferred(self._bot_row(is_active=False))

        assert name.startswith("close_channel_stream:")

    def test_a_bot_in_webhook_mode_has_no_stream_to_open(self):
        """Switching to webhooks has to take the socket down, not leave it up
        beside the endpoint."""
        (name,) = self._deferred(self._bot_row(webhook_mode=True))

        assert name.startswith("close_channel_stream:")

    @pytest.mark.anyio
    async def test_the_stream_is_opened_after_the_commit_not_during_it(self):
        """A connection opened against a row the transaction then rolls back is
        one talking to somebody's Mattermost about a bot that does not exist."""
        service = ChannelBotService(MagicMock(), organization_id=uuid.uuid4())
        with (
            patch("app.services.channel_bot.channel_bot_repo") as bots,
            patch("app.services.channel_bot.spawn_after_commit") as deferred,
            patch("app.services.channel_bot.unseal_bot_token", return_value="tok"),
            patch("app.services.channel_bot.unseal_slack_app_token", return_value=None),
        ):
            bots.create = AsyncMock(return_value=self._bot_row())

            await service.create(
                ChannelBotCreate(
                    platform="mattermost",
                    name="Acme Support",
                    token="a-long-enough-token",
                    api_base_url="https://mattermost.acme.com",
                )
            )

        # Handed over, and not started: `spawn_after_commit` creates the task
        # only once the session has committed, which is what keeps a connection
        # from existing for a row that may still be rolled back.
        assert deferred.call_count == 1
        coro = deferred.call_args.args[1]
        assert not coro.cr_running
        coro.close()

    @pytest.mark.anyio
    async def test_deleting_a_bot_closes_what_it_was_reached_over(self):
        """Read out before the delete: the row is gone by the time this runs, so
        the platform has to be a string the coroutine already holds."""
        service = ChannelBotService(MagicMock(), organization_id=uuid.uuid4())
        bot = self._bot_row()
        with (
            patch("app.services.channel_bot.channel_bot_repo") as bots,
            patch("app.services.channel_bot.spawn_after_commit") as deferred,
        ):
            bots.get_for_org = AsyncMock(return_value=bot)
            bots.delete = AsyncMock()

            await service.delete(bot.id)

        deferred.call_args.args[1].close()
        assert deferred.call_args.kwargs["name"] == f"close_channel_stream:{bot.id}"
