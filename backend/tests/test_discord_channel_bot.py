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
from app.core.exceptions import AuthorizationError, BadRequestError
from app.db.models.channel_bot import ChannelBot
from app.schemas.channel_bot import AccessPolicy, ChannelBotCreate, ChannelBotUpdate
from app.services.channel_bot import ChannelBotService
from app.services.channels.base import IncomingMessage
from app.services.channels.router import ChannelMessageRouter
from app.worker.background import channel as channel_worker

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _audit_trail_is_not_the_test():
    """The service writes the audit trail; a mocked session cannot take the
    advisory lock it chains on, so these tests stand it aside."""
    with patch("app.services.channel_bot.record_audit", new=AsyncMock()):
        yield


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
        await service.update(bot.id, ChannelBotUpdate(**webhook), MagicMock())
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


@pytest.mark.security
class TestPublishingAQuestionAsTheBot:
    """`/ask` posts what was typed as the bot's own message - so only for somebody it answers."""

    def _incoming(self) -> IncomingMessage:
        return IncomingMessage(
            platform="discord",
            bot_id=str(uuid.uuid4()),
            platform_user_id="u1",
            platform_chat_id="c1",
            chat_type="group",
            raw={"guild_id": "100"},
            text="buy now",
            addressed=True,
        )

    def _router(self, bot: MagicMock | None, **steps: AsyncMock) -> ChannelMessageRouter:
        router = ChannelMessageRouter()
        router._resolve_identity = steps.get("identity", AsyncMock())  # type: ignore[method-assign]
        router._sender_is_active_member = steps.get(  # type: ignore[method-assign]
            "member", AsyncMock(return_value=True)
        )
        if bot is not None and isinstance(bot.access_policy, dict):
            bot.access_policy = {"discord_guild_ids": ["100"], **bot.access_policy}
        self._bot = bot
        return router

    async def _ask(self, router: ChannelMessageRouter) -> str | None:
        # The role sync runs first so the membership check sees what the
        # sender's roles give; it has its own tests and reads the database.
        with (
            patch(
                "app.services.channels.router.channel_bot_repo.get_for_inbound",
                AsyncMock(return_value=self._bot),
            ),
            patch.object(ChannelMessageRouter, "_sync_discord_roles", AsyncMock()),
        ):
            return await router.refusal_before_publishing(self._incoming(), MagicMock())

    async def test_a_bot_that_is_gone_publishes_nothing(self):
        assert await self._ask(self._router(None)) == "This bot is not available."
        assert await self._ask(self._router(MagicMock(is_active=False))) == (
            "This bot is not available."
        )

    async def test_the_access_policy_refuses_before_anything_is_posted(self):
        bot = MagicMock(is_active=True, access_policy={"mode": "whitelist", "whitelist": ["x"]})
        refusal = await self._ask(self._router(bot))
        assert refusal == "You are not authorised to use this bot."

    async def test_an_identity_that_is_refused_is_the_refusal(self):
        bot = MagicMock(is_active=True, access_policy={})
        router = self._router(
            bot, identity=AsyncMock(side_effect=AuthorizationError(message="Linked accounts only."))
        )
        assert await self._ask(router) == "Linked accounts only."

    async def test_somebody_nobody_linked_is_asked_to_link_first(self):
        bot = MagicMock(is_active=True, access_policy={"mode": "jwt_linked"})
        router = self._router(bot, member=AsyncMock(return_value=False))
        router._invite_to_link = AsyncMock(return_value="Link first.")  # type: ignore[method-assign]
        with patch.object(router, "_check_rate_limit", AsyncMock()):
            assert await self._ask(router) == "Link first."

    async def test_an_unlinked_ask_cannot_mint_another_link_after_its_rate_limit(self) -> None:
        bot = MagicMock(is_active=True, access_policy={"mode": "jwt_linked"})
        router = self._router(bot, member=AsyncMock(return_value=False))
        with (
            patch.object(
                router,
                "_check_rate_limit",
                AsyncMock(side_effect=BadRequestError(message="Slow down.")),
            ) as limit,
            patch.object(
                router, "_invite_to_link", AsyncMock(return_value="New bearer link")
            ) as invite,
        ):
            assert await self._ask(router) == "Slow down."
            limit.assert_awaited_once()
            invite.assert_not_awaited()

    async def test_a_ready_installation_is_not_an_operator_server_approval(self) -> None:
        bot = MagicMock(is_active=True, access_policy={"discord_guild_ids": []})
        identity = AsyncMock()
        router = self._router(bot, identity=identity)
        assert await self._ask(router) == "This Discord server is not approved for this bot."
        identity.assert_not_awaited()

    async def test_somebody_it_answers_is_let_through(self):
        assert await self._ask(self._router(MagicMock(is_active=True, access_policy={}))) is None

    async def test_a_failure_to_decide_is_a_refusal_not_a_post(self):
        @asynccontextmanager
        async def broken() -> AsyncIterator[MagicMock]:
            raise RuntimeError("database down")
            yield MagicMock()

        with patch.object(channel_worker, "get_db_context", broken):
            refusal = await channel_worker.refusal_before_publishing(self._incoming())
        assert refusal is not None and "Try again" in refusal

    async def test_the_worker_hands_the_decision_to_the_router(self):
        @asynccontextmanager
        async def session() -> AsyncIterator[MagicMock]:
            yield MagicMock()

        with (
            patch.object(channel_worker, "get_db_context", session),
            patch.object(
                ChannelMessageRouter, "refusal_before_publishing", AsyncMock(return_value="no")
            ),
        ):
            assert await channel_worker.refusal_before_publishing(self._incoming()) == "no"


class TestAGroupOnlyBotAndTheRoomsOfThreads:
    """A conversation key folds a thread in; a group is listed under its channel."""

    def _check(self, key: str) -> None:
        incoming = IncomingMessage(
            platform="discord",
            bot_id="b",
            platform_user_id="u",
            platform_chat_id=key,
            chat_type="group",
            raw={"guild_id": "999"},
            text="hi",
        )
        bot = MagicMock(
            access_policy={
                "mode": "group_only",
                "allowed_groups": ["100"],
                "discord_guild_ids": ["999"],
            }
        )
        ChannelMessageRouter()._check_access(incoming, bot)

    def test_a_channel_listed_by_its_id_admits_its_threads(self):
        self._check("100")
        self._check("100:555")

    def test_another_channel_is_refused_thread_or_not(self):
        with pytest.raises(AuthorizationError):
            self._check("200")
        with pytest.raises(AuthorizationError):
            self._check("200:100")


@pytest.mark.security
async def test_server_approvals_are_rejected_before_writing_a_non_discord_bot() -> None:
    service = ChannelBotService(MagicMock(), organization_id=uuid.uuid4())
    data = ChannelBotCreate(
        platform="slack",
        name="bot",
        token="t" * 40,
        access_policy=AccessPolicy(discord_guild_ids=["100"]),
    )
    with patch("app.services.channel_bot.channel_bot_repo.create", AsyncMock()) as saved:
        with pytest.raises(BadRequestError) as failure:
            await service.create(data)
        assert failure.value.details["fields"][0]["field"] == "access_policy.discord_guild_ids"
        saved.assert_not_awaited()


@pytest.mark.security
async def test_an_update_cannot_store_discord_approvals_on_another_platform() -> None:
    row = _row()
    row.platform = "telegram"
    service = ChannelBotService(MagicMock(), organization_id=row.organization_id)
    with (
        patch("app.services.channel_bot.channel_bot_repo.get_for_org", AsyncMock(return_value=row)),
        patch("app.services.channel_bot.channel_bot_repo.update", AsyncMock()) as saved,
    ):
        with pytest.raises(BadRequestError):
            await service.update(
                row.id,
                ChannelBotUpdate(access_policy=AccessPolicy(discord_guild_ids=["100"])),
                MagicMock(),
            )
        saved.assert_not_awaited()


@pytest.mark.security
def test_cli_persists_each_explicitly_approved_server() -> None:
    bot = _row()
    saved = AsyncMock(return_value=bot)
    service = MagicMock(create=saved)

    @asynccontextmanager
    async def provided(org_id: str | None) -> AsyncIterator[MagicMock]:
        assert org_id == "org-for-test"
        yield service

    with patch.object(channel_commands, "_channel_service", provided):
        result = CliRunner().invoke(
            channel_commands.channel_add_bot,
            [
                "--platform",
                "discord",
                "--name",
                "bot",
                "--token",
                "t" * 40,
                "--org",
                "org-for-test",
                "--discord-guild",
                "100",
                "--discord-guild",
                "200",
            ],
        )
    assert result.exception is None, result.output
    call = saved.await_args
    assert call is not None
    data = call.args[0]
    assert isinstance(data, ChannelBotCreate)
    assert data.access_policy.discord_guild_ids == ["100", "200"]


@pytest.mark.security
def test_an_existing_policy_without_server_approvals_still_loads_as_dm_only() -> None:
    policy = AccessPolicy.model_validate({"mode": "open", "rate_limit_rpm": 3})
    assert policy.discord_guild_ids == []
    assert policy.rate_limit_rpm == 3


@pytest.mark.security
def test_server_names_are_not_accepted_as_an_approval() -> None:
    with pytest.raises(ValidationError):
        AccessPolicy(discord_guild_ids=["my-server"])
