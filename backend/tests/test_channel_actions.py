"""Explicit cross-channel grants are live, tenant scoped and separate from inbound tools."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.channel_actions._contract import TOOLS
from app.agents.capabilities.channel_actions._toolset import build_channel_actions
from app.agents.capabilities.channel_tools._directory import (
    ChannelListPage,
    ChannelPost,
    ChannelSummary,
    HistoryPage,
)
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError, ExternalServiceError
from app.core.permissions import AuthContext
from app.db.models.agent_exposure import AgentExposure
from app.db.models.channel_bot import ChannelBot
from app.services.channel_actions import (
    ChannelActionService,
    grant_fingerprint,
    granted_connections,
    with_actions,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def setup():
    db = AsyncMock(spec=AsyncSession)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    agent_id = uuid4()
    bot = ChannelBot(
        id=uuid4(),
        organization_id=ctx.organization_id,
        name="Reports",
        platform="mattermost",
        is_active=True,
        authorization_generation=uuid4(),
        api_base_url="https://messages.example",
    )
    exposure = AgentExposure(
        id=uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent_id,
        channel_bot_id=bot.id,
        surface="mattermost",
        is_active=True,
        tools=list(TOOLS),
    )
    adapter = MagicMock(platform="mattermost")
    adapter.joined_channels = AsyncMock(
        return_value=ChannelListPage((ChannelSummary("room", "Reports"),), "next")
    )
    adapter.require_joined_channel = AsyncMock()
    adapter.require_channel_thread = AsyncMock()
    adapter.send_message = AsyncMock()
    adapter.channel_history_page = AsyncMock(
        return_value=HistoryPage((ChannelPost("Alice", "Evidence"),), 1)
    )

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        yield db

    with (
        patch("app.services.channel_actions.get_db_context", context),
        patch(
            "app.services.channel_actions.member_repo.get_active",
            AsyncMock(return_value=MagicMock(role="owner")),
        ) as member,
        patch("app.services.channel_actions.AgentRegistryService.get", AsyncMock()) as agent,
        patch(
            "app.services.channel_actions.agent_exposure_repo.list_for_agent",
            AsyncMock(return_value=[exposure]),
        ) as bindings,
        patch(
            "app.services.channel_actions.channel_bot_repo.get_for_org", AsyncMock(return_value=bot)
        ),
        patch("app.services.channel_actions.get_adapter", return_value=adapter),
        patch("app.services.channel_actions.unseal_bot_token", return_value="private-token"),
    ):
        yield db, ctx, agent_id, bot, exposure, adapter, member, agent, bindings


@pytest.mark.security
async def test_grants_are_opt_in_and_rechecked_after_revocation(setup):
    db, ctx, agent_id, bot, exposure, adapter, *_ = setup
    service = ChannelActionService(ctx, agent_id)
    assert await service.tools(db) == TOOLS
    listing = json.loads(await service.connections())
    assert listing["connections"][0]["bot_id"] == str(bot.id) and "private-token" not in json.dumps(
        listing
    )
    await service.send(bot.id, "room", text="Requested report", thread_id="root")
    adapter.require_joined_channel.assert_awaited_once()
    adapter.require_channel_thread.assert_awaited_once()
    assert adapter.send_message.await_args.args[1].platform_chat_id == "room:root"
    exposure.tools = ["find_chat_channels"]
    with pytest.raises(AuthorizationError):
        await service.send(bot.id, "room", text="No longer authorized", thread_id=None)
    assert adapter.send_message.await_count == 1
    assert await service.tools(db) == {"list_chat_connections", "find_chat_channels"}


@pytest.mark.security
@pytest.mark.parametrize(
    "changed", ["bot_off", "binding_off", "other_platform", "no_tools", "wrong_bot"]
)
async def test_inactive_or_mismatched_bindings_grant_nothing(setup, changed):
    db, ctx, agent_id, bot, exposure, adapter, *_ = setup
    if changed == "bot_off":
        bot.is_active = False
    if changed == "binding_off":
        exposure.is_active = False
    if changed == "other_platform":
        exposure.surface = "telegram"
    if changed == "no_tools":
        exposure.tools = []
    if changed == "wrong_bot":
        bot.platform = "slack"
    assert (
        await granted_connections(db, organization_id=ctx.organization_id, agent_id=agent_id) == {}
    )
    assert await ChannelActionService(ctx, agent_id).tools(db) == frozenset()
    adapter.send_message.assert_not_awaited()


@pytest.mark.security
async def test_routine_tools_are_limited_to_the_exact_reviewed_connection_grants(setup):
    db, ctx, agent_id, bot, exposure, *_ = setup
    service = ChannelActionService(ctx, agent_id)
    reviewed = {exposure.id: grant_fingerprint(exposure, bot)}
    assert await service.tools(db, reviewed=reviewed) == TOOLS
    bot.authorization_generation = uuid4()
    assert not await service.tools(db, reviewed=reviewed)
    assert not await service.tools(db, reviewed={})


@pytest.mark.security
@pytest.mark.parametrize("who", ["anonymous", "fallback", "removed", "no_agent_access"])
async def test_an_unidentified_or_revoked_actor_never_reaches_the_bot(setup, who):
    _, ctx, agent_id, bot, _, adapter, member, agent, _ = setup
    if who == "anonymous":
        ctx = AuthContext(user_id=None, organization_id=ctx.organization_id, role="viewer")
    if who == "fallback":
        ctx = AuthContext(
            user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            role="owner",
            subject_is_publisher_fallback=True,
        )
    if who == "removed":
        member.return_value = None
    if who == "no_agent_access":
        agent.side_effect = AuthorizationError()
    with pytest.raises(AuthorizationError):
        await ChannelActionService(ctx, agent_id).send(
            bot.id, "room", text="Do not send", thread_id=None
        )
    adapter.send_message.assert_not_awaited()


async def test_lookup_pages_and_message_filters_remain_bounded(setup):
    _, ctx, agent_id, bot, _, adapter, *_ = setup
    service = ChannelActionService(ctx, agent_id)
    assert json.loads(await service.find(bot.id, "reports", 20, None))["next_cursor"] == "next"
    page = await service.read(
        bot.id,
        "room",
        thread_id=None,
        query="Evidence",
        after=None,
        before=None,
        author_id="alice",
        cursor=None,
        limit=20,
    )
    assert page.posts[0].text == "Evidence"
    assert adapter.channel_history_page.await_args.kwargs["filters"].author_id == "alice"
    assert adapter.channel_history_page.await_args.kwargs["thread_id"] is None


@pytest.mark.security
@pytest.mark.parametrize(
    "channel,thread,text",
    [
        ("../other", None, "report"),
        ("room", "wrong/root", "report"),
        ("room", None, ""),
        ("room", None, "x" * 12001),
    ],
)
async def test_malformed_destinations_and_unbounded_messages_are_refused(
    setup, channel, thread, text
):
    _, ctx, agent_id, bot, _, adapter, *_ = setup
    with pytest.raises(BadRequestError):
        await ChannelActionService(ctx, agent_id).send(bot.id, channel, text=text, thread_id=thread)
    adapter.send_message.assert_not_awaited()


async def test_provider_failures_are_explicit_and_an_uncertain_send_is_not_retried(setup):
    _, ctx, agent_id, bot, _, adapter, *_ = setup
    service = ChannelActionService(ctx, agent_id)
    adapter.send_message.side_effect = httpx.ReadTimeout("sensitive provider URL")
    with pytest.raises(ExternalServiceError, match="Check the destination") as found:
        await service.send(bot.id, "room", text="report", thread_id=None)
    assert "sensitive" not in found.value.message
    assert adapter.send_message.await_count == 1
    adapter.joined_channels.side_effect = httpx.ReadTimeout("sensitive")
    with pytest.raises(ExternalServiceError, match="not an empty result"):
        await service.find(bot.id, "report", 10, None)
    adapter.require_joined_channel.side_effect = httpx.ReadTimeout("sensitive")
    with pytest.raises(ExternalServiceError, match="no messages were read"):
        await service.read(
            bot.id,
            "room",
            thread_id=None,
            query="",
            after=None,
            before=None,
            author_id=None,
            cursor=None,
            limit=20,
        )


def test_runtime_bindings_do_not_mutate_the_published_spec():
    spec = AgentSpec(name="Example")
    changed = with_actions(spec, frozenset({"find_chat_channels"}))
    assert all(binding.id != "channel_actions" for binding in spec.capabilities)
    assert changed.capabilities[-1].config == {"tools": ["find_chat_channels"]}
    assert with_actions(changed, frozenset()).capabilities == spec.capabilities


async def test_real_tool_contract_excerpts_results_and_clamps_requests():
    port = MagicMock()
    port.read = AsyncMock(
        return_value=HistoryPage((ChannelPost("Alice", "x" * 1000),), 100, "cursor")
    )
    port.find = AsyncMock(return_value='{"channels":[],"next_cursor":"older"}')
    port.send = AsyncMock(return_value="accepted")
    port.connections = AsyncMock(return_value="[]")
    tools = build_channel_actions(port, TOOLS)
    context = RunContext(deps=AgentDeps(), model=TestModel(), usage=RunUsage())
    built = await tools.get_tools(context)
    assert set(built) == TOOLS
    bot_id = str(uuid4())
    result = await tools.call_tool(
        "read_chat_messages",
        {"bot_id": bot_id, "channel_id": "room", "limit": 9999},
        context,
        built["read_chat_messages"],
    )
    assert len(result) < 700 and '"next_cursor": "cursor"' in result
    assert port.read.await_args.kwargs["limit"] == 100
    await tools.call_tool(
        "find_chat_channels",
        {"bot_id": bot_id, "limit": 9999},
        context,
        built["find_chat_channels"],
    )
    assert port.find.await_args.args[2] == 100
    for name, args in [
        ("list_chat_connections", {}),
        ("send_chat_message", {"bot_id": bot_id, "channel_id": "room", "text": "report"}),
    ]:
        await tools.call_tool(name, args, context, built[name])


@pytest.mark.parametrize("platform", ["telegram", "discord", "imessage"])
@pytest.mark.security
async def test_reaction_only_platforms_cannot_inherit_cross_channel_grants(setup, platform):
    from app.agents.capabilities.channel_tools._directory import ChannelDestination

    db, ctx, agent_id, bot, exposure, adapter, *_ = setup
    bot.platform = exposure.surface = platform
    adapter.react_to_message = AsyncMock()
    destination = ChannelDestination(
        bot_id=bot.id, platform_chat_id="room", private_chat=False, message_id="question"
    )
    service = ChannelActionService(ctx, agent_id, destination=destination)
    assert await service.tools(db) == {"list_chat_connections", "react_to_chat_message"}
    with pytest.raises(AuthorizationError):
        await service.send(bot.id, "room", text="Not granted on this transport", thread_id=None)
    receipt = json.loads(
        await service.react(bot.id, "room", "question", ["heart"], reaction_only=True)
    )
    assert receipt["applied"] == ["heart"] and receipt["reaction_only"]
    adapter.require_joined_channel.assert_not_awaited()
    with pytest.raises(AuthorizationError):
        await service.react(bot.id, "another-room", "question", ["heart"], reaction_only=True)
    with pytest.raises(AuthorizationError):
        await service.react(bot.id, "room", "another-message", ["heart"], reaction_only=True)
    assert adapter.react_to_message.await_count == 1


@pytest.mark.parametrize("platform", ["teams", "sms", "email"])
async def test_no_unimplemented_reaction_or_cross_channel_tools_are_injected(setup, platform):
    db, ctx, agent_id, bot, exposure, *_ = setup
    bot.platform = exposure.surface = platform
    service = ChannelActionService(ctx, agent_id)
    assert await service.tools(db) == frozenset()
    assert json.loads(await service.connections())["connections"] == []


@pytest.mark.parametrize("platform", ["telegram", "imessage"])
async def test_single_reaction_platform_refuses_multiple_before_any_effect(setup, platform):
    from app.agents.capabilities.channel_tools._directory import ChannelDestination

    _, ctx, agent_id, bot, exposure, adapter, *_ = setup
    bot.platform = exposure.surface = platform
    adapter.react_to_message = AsyncMock()
    service = ChannelActionService(
        ctx,
        agent_id,
        destination=ChannelDestination(
            bot_id=bot.id, platform_chat_id="room", private_chat=False, message_id="question"
        ),
    )
    with pytest.raises(BadRequestError, match="one bot reaction"):
        await service.react(bot.id, "room", "question", ["heart", "thumbsup"], reaction_only=True)
    adapter.react_to_message.assert_not_awaited()


async def test_multiple_reactions_are_deduplicated_and_partial_failure_is_explicit(setup):
    _, ctx, agent_id, bot, _, adapter, *_ = setup
    adapter.react_to_message = AsyncMock(side_effect=[None, httpx.ReadTimeout("unconfirmed")])
    receipt = json.loads(
        await ChannelActionService(ctx, agent_id).react(
            bot.id, "room", "question", ["heart", "heart", "thumbsup", "tada"], reaction_only=True
        )
    )
    assert receipt["applied"] == ["heart"]
    assert receipt["failed"] == ["thumbsup"]
    assert receipt["not_attempted"] == ["tada"]
    assert not receipt["reaction_only"]
    assert adapter.react_to_message.await_count == 2
