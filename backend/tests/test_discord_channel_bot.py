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
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotUpdate
from app.services.channel_bot import ChannelBotService
from app.services.channels.base import IncomingMessage
from app.services.channels.router import ChannelMessageRouter
from app.worker.background import channel as channel_worker

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


class TestPublishingAQuestionAsTheBot:
    """`/ask` posts what was typed as the bot's own message - so only for somebody it answers."""

    def _incoming(self) -> IncomingMessage:
        return IncomingMessage(
            platform="discord",
            bot_id=str(uuid.uuid4()),
            platform_user_id="u1",
            platform_chat_id="c1",
            chat_type="group",
            text="buy now",
            addressed=True,
        )

    def _router(self, bot: MagicMock | None, **steps: AsyncMock) -> ChannelMessageRouter:
        router = ChannelMessageRouter()
        router._resolve_identity = steps.get("identity", AsyncMock())  # type: ignore[method-assign]
        router._sender_is_active_member = steps.get(  # type: ignore[method-assign]
            "member", AsyncMock(return_value=True)
        )
        self._bot = bot
        return router

    async def _ask(self, router: ChannelMessageRouter) -> str | None:
        with patch(
            "app.services.channels.router.channel_bot_repo.get_for_inbound",
            AsyncMock(return_value=self._bot),
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
        assert await self._ask(router) == "Link first."

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
            text="hi",
        )
        bot = MagicMock(access_policy={"mode": "group_only", "allowed_groups": ["100"]})
        ChannelMessageRouter()._check_access(incoming, bot)

    def test_a_channel_listed_by_its_id_admits_its_threads(self):
        self._check("100")
        self._check("100:555")

    def test_another_channel_is_refused_thread_or_not(self):
        with pytest.raises(AuthorizationError):
            self._check("200")
        with pytest.raises(AuthorizationError):
            self._check("200:100")
