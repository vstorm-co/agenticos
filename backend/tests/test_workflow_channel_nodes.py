"""The channel steps: act as one of the organization's bots, through its adapter.

The adapter is a stand-in with the platform calls the steps make; what is under
test is what each step sends, what it hands on, and every way it refuses - a
bot that is gone or off, a member without `channels:manage`, a platform that
does not let a bot do what was asked, a platform that did not answer.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.agents.capabilities.channel_tools._directory import (
    ChannelDirectoryUnsupported,
    ChannelMember,
    ChannelPost,
    ChannelSummary,
)
from app.core.permissions import AuthContext
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.slack import SlackAdapter
from app.services.channels.telegram import TelegramAdapter
from app.services.workflow_execution import context
from app.workflows._registry import REGISTRY, load_builtins
from app.workflows.contracts.results import Completed, Failed
from app.workflows.nodes import _channels
from app.workflows.nodes._channels import ChannelBotConfig, check_bot_on, check_listening_bot
from app.workflows.nodes.channel_find._handler import ChannelFindConfig, ChannelFindInput
from app.workflows.nodes.channel_find._handler import handler_on as find_on
from app.workflows.nodes.channel_members._handler import ChannelMembersConfig, ChannelMembersInput
from app.workflows.nodes.channel_members._handler import handler_on as members_on
from app.workflows.nodes.channel_read._handler import ChannelReadConfig, ChannelReadInput
from app.workflows.nodes.channel_read._handler import handler_on as read_on
from app.workflows.nodes.channel_send._handler import ChannelSendInput
from app.workflows.nodes.channel_send._handler import handler_on as send_on

pytestmark = pytest.mark.anyio

BOT = {"bot_id": str(uuid.uuid4())}

# The stand-in bot is a Mattermost one, so these are the Mattermost steps.
send, read, members, find = (
    send_on("mattermost"),
    read_on("mattermost"),
    members_on("mattermost"),
    find_on("mattermost"),
)


def _dispatch() -> context.DispatchContext:
    return context.DispatchContext(
        organization_id=uuid.uuid4(),
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner"),
        resumed_agent_run_id=None,
    )


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """A Mattermost bot the principal may act as, behind a stand-in adapter."""
    platform = MagicMock()
    bot = MagicMock(platform="mattermost", api_base_url="https://chat.example.com")

    @asynccontextmanager
    async def session() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    monkeypatch.setattr(_channels, "get_worker_db_context", session)
    monkeypatch.setattr(_channels, "_usable_bot", AsyncMock(return_value=bot))
    monkeypatch.setattr(_channels, "get_adapter", lambda name: platform)
    monkeypatch.setattr(_channels, "unseal_bot_token", lambda _bot: "bot-token")
    platform.bot = bot
    return platform


@pytest.fixture
def bot_on(monkeypatch: pytest.MonkeyPatch):
    """Make a bot of a platform usable, behind the given adapter instance."""

    def make(platform: str, adapter_instance: Any) -> None:
        bot = MagicMock(platform=platform, api_base_url="https://chat.example.com")

        @asynccontextmanager
        async def session() -> AsyncIterator[MagicMock]:
            yield MagicMock()

        monkeypatch.setattr(_channels, "get_worker_db_context", session)
        monkeypatch.setattr(_channels, "_usable_bot", AsyncMock(return_value=bot))
        monkeypatch.setattr(_channels, "get_adapter", lambda name: adapter_instance)
        monkeypatch.setattr(_channels, "unseal_bot_token", lambda _bot: "bot-token")

    return make


async def _run(handle, config, node_input) -> Any:
    with context.dispatching_as(_dispatch()):
        return await handle(config, node_input)


class TestSend:
    async def test_the_message_goes_out_as_the_bot_to_the_channel_and_thread(self, adapter):
        adapter.send_message = AsyncMock()
        result = await _run(
            send,
            ChannelBotConfig.model_validate(BOT),
            ChannelSendInput(channel_id="c-1", text="Deploy done", thread_id="t-9"),
        )

        assert isinstance(result, Completed)
        assert result.output.model_dump() == {"channel_id": "c-1", "thread_id": "t-9"}
        token, message = adapter.send_message.await_args.args
        assert token == "bot-token"
        assert (message.platform_chat_id, message.text, message.reply_to_message_id) == (
            "c-1:t-9",
            "Deploy done",
            None,
        )
        assert message.api_base_url == "https://chat.example.com"

    async def test_a_platform_that_does_not_answer_is_retryable_and_quotes_no_token(self, adapter):
        adapter.send_message = AsyncMock(side_effect=RuntimeError("401 token=bot-token"))
        result = await _run(
            send, ChannelBotConfig.model_validate(BOT), ChannelSendInput(channel_id="c", text="x")
        )
        assert isinstance(result, Failed) and result.error.code == "CHANNEL_CALL_FAILED"
        assert result.error.retryable is True
        assert "bot-token" not in str(result.error)


class TestSendIntoAThread:
    async def test_a_slack_reply_lands_in_the_thread(self, bot_on):
        client = MagicMock(chat_postMessage=AsyncMock())
        bot_on("slack", SlackAdapter())
        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=client):
            result = await _run(
                send_on("slack"),
                ChannelBotConfig.model_validate(BOT),
                ChannelSendInput(channel_id="C1", text="Deploy done", thread_id="1700.1"),
            )
        assert isinstance(result, Completed)
        assert client.chat_postMessage.await_args.kwargs == {
            "channel": "C1",
            "text": "Deploy done",
            "thread_ts": "1700.1",
        }

    async def test_a_mattermost_reply_lands_under_its_root_post(self, bot_on, monkeypatch):
        client = MagicMock(post=AsyncMock(return_value=MagicMock(raise_for_status=lambda: None)))
        monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: client)
        bot_on("mattermost", MattermostAdapter())
        result = await _run(
            send_on("mattermost"),
            ChannelBotConfig.model_validate(BOT),
            ChannelSendInput(channel_id="c1", text="Deploy done", thread_id="root9"),
        )
        assert isinstance(result, Completed)
        assert client.post.await_args.args[0] == "https://chat.example.com/api/v4/posts"
        assert client.post.await_args.kwargs["json"] == {
            "channel_id": "c1",
            "message": "Deploy done",
            "root_id": "root9",
        }

    @staticmethod
    def _telegram(bot_on) -> MagicMock:
        bot = MagicMock(send_message=AsyncMock())
        bot.session.close = AsyncMock()
        bot_on("telegram", TelegramAdapter())
        return bot

    async def test_a_telegram_reply_lands_in_the_forum_topic(self, bot_on):
        bot = self._telegram(bot_on)
        with patch("app.services.channels.telegram.Bot", return_value=bot):
            result = await _run(
                send_on("telegram"),
                ChannelBotConfig.model_validate(BOT),
                ChannelSendInput(channel_id="-1001234", text="hi", thread_id="7"),
            )
        assert isinstance(result, Completed)
        kwargs = bot.send_message.await_args.kwargs
        assert (kwargs["chat_id"], kwargs["message_thread_id"], kwargs["reply_to_message_id"]) == (
            "-1001234",
            7,
            None,
        )

    async def test_a_telegram_reply_with_no_thread_goes_to_the_chat(self, bot_on):
        bot = self._telegram(bot_on)
        with patch("app.services.channels.telegram.Bot", return_value=bot):
            result = await _run(
                send_on("telegram"),
                ChannelBotConfig.model_validate(BOT),
                ChannelSendInput(channel_id="-1001234", text="hi", thread_id=""),
            )
        assert isinstance(result, Completed)
        assert "message_thread_id" not in bot.send_message.await_args.kwargs
        assert bot.send_message.await_args.kwargs["chat_id"] == "-1001234"

    @pytest.mark.parametrize(
        ("platform", "channel_id", "thread_id"),
        [
            ("telegram", "-1001234", "1700.1"),
            ("telegram", "-1001234", "abc"),
            ("slack", "C1:1700.1", None),
            ("mattermost", "c1:root9", "root9"),
            ("slack", "C1", "1700.1:x"),
            ("mattermost", "c1", "root9:x"),
        ],
        ids=[
            "telegram-dotted",
            "telegram-word",
            "slack-colon",
            "mattermost-colon",
            "slack-thread-colon",
            "mattermost-thread-colon",
        ],
    )
    async def test_a_target_the_platform_cannot_address_is_refused_before_sending(
        self, bot_on, platform, channel_id, thread_id
    ):
        adapter_instance = MagicMock(send_message=AsyncMock())
        bot_on(platform, adapter_instance)
        result = await _run(
            send_on(platform),
            ChannelBotConfig.model_validate(BOT),
            ChannelSendInput(channel_id=channel_id, text="x", thread_id=thread_id),
        )
        assert isinstance(result, Failed) and result.error.code == "CHANNEL_TARGET_INVALID"
        assert result.error.retryable is False
        adapter_instance.send_message.assert_not_awaited()


class TestRead:
    async def test_the_messages_come_back_oldest_first(self, adapter):
        at = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
        adapter.channel_history = AsyncMock(
            return_value=[ChannelPost(author="ada", text="hi", posted_at=at, post_id="p1")]
        )
        result = await _run(
            read,
            ChannelReadConfig.model_validate({**BOT, "limit": 10}),
            ChannelReadInput(channel_id="c-1", thread_id="t-1"),
        )

        assert result.output.model_dump() == {
            "messages": ({"author": "ada", "text": "hi", "posted_at": at, "post_id": "p1"},)
        }
        assert adapter.channel_history.await_args.kwargs == {
            "api_base_url": "https://chat.example.com",
            "limit": 10,
            "thread_id": "t-1",
        }

    async def test_a_platform_that_keeps_history_from_a_bot_says_so(self, adapter):
        adapter.bot.platform = "telegram"
        adapter.channel_history = AsyncMock(
            side_effect=ChannelDirectoryUnsupported("telegram does not let a bot read history")
        )
        result = await _run(
            read, ChannelReadConfig.model_validate(BOT), ChannelReadInput(channel_id="c")
        )
        assert isinstance(result, Failed) and result.error.code == "CHANNEL_UNSUPPORTED"
        assert result.error.details == {"platform": "telegram"}


class TestMembersAndFind:
    async def test_the_people_in_a_channel_come_with_their_platform_ids(self, adapter):
        adapter.channel_members = AsyncMock(
            return_value=[ChannelMember(user_id="u1", username="ada", display_name="Ada")]
        )
        result = await _run(
            members,
            ChannelMembersConfig.model_validate(BOT),
            ChannelMembersInput(channel_id="c-1"),
        )
        assert result.output.members[0].model_dump() == {
            "user_id": "u1",
            "username": "ada",
            "display_name": "Ada",
            "is_bot": False,
            "role": None,
        }
        assert adapter.channel_members.await_args.kwargs["limit"] == 100

    async def test_channels_are_found_by_name_from_a_channel_the_bot_is_in(self, adapter):
        adapter.search_channels = AsyncMock(
            return_value=[ChannelSummary(channel_id="c-2", name="ops", purpose="Incidents")]
        )
        result = await _run(
            find,
            ChannelFindConfig.model_validate(BOT),
            ChannelFindInput(query="op", channel_id="c-1"),
        )
        assert result.output.channels[0].model_dump() == {
            "channel_id": "c-2",
            "name": "ops",
            "purpose": "Incidents",
            "is_private": None,
        }
        assert adapter.search_channels.await_args.kwargs["query"] == "op"


class TestRefusals:
    @pytest.mark.parametrize(
        ("handle", "config", "node_input"),
        [
            (
                send,
                ChannelBotConfig.model_validate(BOT),
                ChannelSendInput(channel_id="c", text="x"),
            ),
            (read, ChannelReadConfig.model_validate(BOT), ChannelReadInput(channel_id="c")),
            (
                members,
                ChannelMembersConfig.model_validate(BOT),
                ChannelMembersInput(channel_id="c"),
            ),
            (find, ChannelFindConfig.model_validate(BOT), ChannelFindInput(channel_id="c")),
        ],
        ids=["send", "read", "members", "find"],
    )
    async def test_an_unconfigured_step_or_an_unusable_bot_acts_on_nothing(
        self, adapter, monkeypatch, handle, config, node_input
    ):
        unconfigured = await _run(handle, None, None)
        assert isinstance(unconfigured, Failed)
        assert unconfigured.error.code == "CHANNEL_NOT_CONFIGURED"

        monkeypatch.setattr(_channels, "_usable_bot", AsyncMock(return_value=None))
        refused = await _run(handle, config, node_input)
        assert isinstance(refused, Failed) and refused.error.code == "CHANNEL_NOT_USABLE"
        assert adapter.method_calls == []


class TestWhoMayActAsABot:
    def _ctx(self, role: str) -> AuthContext:
        return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("role", "bot", "usable"),
        [
            ("owner", MagicMock(is_active=True, platform="slack"), True),
            ("owner", MagicMock(is_active=True, platform="mattermost"), False),
            ("owner", MagicMock(is_active=False, platform="slack"), False),
            ("owner", None, False),
            ("viewer", MagicMock(is_active=True, platform="slack"), False),
        ],
        ids=["active", "another-platform", "switched-off", "gone", "no-channels-manage"],
    )
    async def test_only_a_member_who_manages_channels_acts_as_an_active_bot_of_the_platform(
        self, monkeypatch, role, bot, usable
    ):
        lookup = AsyncMock(return_value=bot)
        monkeypatch.setattr(_channels.channel_bot_repo, "get_for_org", lookup)

        problems = await check_bot_on("slack")(
            MagicMock(), self._ctx(role), ChannelBotConfig.model_validate(BOT)
        )

        assert (problems == []) is usable
        if not usable:
            assert problems[0][0] == "bot_id" and "Slack bot" in problems[0][1]
        if role == "viewer":
            # Refused before the bot is even looked up.
            lookup.assert_not_awaited()

    @pytest.mark.security
    async def test_a_teams_bot_cannot_start_a_workflow(self, monkeypatch):
        monkeypatch.setattr(
            _channels.channel_bot_repo,
            "get_for_org",
            AsyncMock(return_value=MagicMock(is_active=True, platform="teams")),
        )
        problems = await check_listening_bot(
            MagicMock(), self._ctx("owner"), ChannelBotConfig.model_validate(BOT)
        )
        assert problems == [
            (
                "bot_id",
                "A workflow cannot listen to a Teams bot - choose a Slack, Mattermost "
                "or Telegram bot",
            )
        ]

    async def test_a_slack_bot_still_starts_one(self, monkeypatch):
        monkeypatch.setattr(
            _channels.channel_bot_repo,
            "get_for_org",
            AsyncMock(return_value=MagicMock(is_active=True, platform="slack")),
        )
        assert (
            await check_listening_bot(
                MagicMock(), self._ctx("owner"), ChannelBotConfig.model_validate(BOT)
            )
            == []
        )

    async def test_a_config_of_another_step_is_not_this_checks_to_judge(self):
        assert await check_bot_on("slack")(MagicMock(), MagicMock(), MagicMock()) == []


class TestThePlatformSteps:
    def test_each_platform_has_the_steps_its_bots_can_take(self):
        load_builtins()
        steps = {
            key for key in REGISTRY if key.split(".")[0] in {"slack", "mattermost", "telegram"}
        }
        assert steps == {
            *(
                f"{p}.{op}"
                for p in ("slack", "mattermost")
                for op in ("message.send", "messages.read", "members.list", "channels.find")
            ),
            "telegram.message.send",
            "telegram.members.list",
        }

    def test_a_step_offers_only_its_platforms_bots(self):
        load_builtins()
        definition = REGISTRY["telegram.members.list"][1]
        assert definition.name == "List administrators"
        assert definition.category == "telegram"
        field = definition.config_schema.model_json_schema()["properties"]["bot_id"]
        assert (field["x-resource"], field["x-platform"], field["title"]) == (
            "channel_bot",
            "telegram",
            "Telegram bot",
        )
