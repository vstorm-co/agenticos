"""Native reactions use the provider protocol, with explicit transport limits."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import unquote

import httpx
import pytest

from app.agents.capabilities.channel_actions._contract import platform_actions
from app.agents.capabilities.channel_tools import ChannelDirectoryUnsupported
from app.services.channels.discord import DiscordAdapter
from app.services.channels.imessage import ImessageAdapter
from app.services.channels.telegram import TelegramAdapter
from tests.test_imessage import credential

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "platform", ["mattermost", "slack", "telegram", "discord", "imessage", "teams", "sms", "email"]
)
async def test_new_binding_defaults_match_actual_platform_actions(platform: str) -> None:
    from app.db.models.agent_exposure import ExposureSurface
    from app.services.agent_exposure import _lookups_for

    offered = {tool.id for tool in await _lookups_for(ExposureSurface(platform))}
    assert ("react_to_chat_message" in offered) == (
        platform in {"mattermost", "slack", "telegram", "discord", "imessage"}
    )
    assert platform_actions(platform) - {"list_chat_connections"} <= offered


async def test_telegram_sends_one_native_reaction_and_deletes_progress() -> None:
    bot = MagicMock(set_message_reaction=AsyncMock(), delete_message=AsyncMock())

    @asynccontextmanager
    async def client(token: str):
        assert token == "private-token"
        yield bot

    adapter = TelegramAdapter()
    with patch.object(adapter, "_bot", client):
        await adapter.react_to_message("private-token", "-10042", "7", "heart", api_base_url=None)
        assert bot.set_message_reaction.await_args.kwargs["reaction"][0].emoji == "❤"
        assert bot.set_message_reaction.await_args.kwargs["message_id"] == 7
        await adapter.delete_reply("private-token", "-10042:3", "8", api_base_url=None)
        bot.delete_message.assert_awaited_once_with(chat_id="-10042", message_id=8)
        with pytest.raises(ChannelDirectoryUnsupported):
            await adapter.react_to_message(
                "private-token", "-10042", "7", "unknown", api_base_url=None
            )
        assert bot.set_message_reaction.await_count == 1


async def test_discord_reactions_are_url_encoded_and_acknowledged_by_http() -> None:
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(204)

    adapter = DiscordAdapter()
    await adapter._http.aclose()
    adapter._http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await adapter.react_to_message("private-token", "42", "7", "heart", api_base_url=None)
        assert calls[0].method == "PUT"
        assert unquote(calls[0].url.path).endswith("/channels/42/messages/7/reactions/❤/@me")
        assert calls[0].headers["authorization"] == "Bot private-token"
        with pytest.raises(ChannelDirectoryUnsupported):
            await adapter.react_to_message(
                "private-token", "../42", "7", "heart", api_base_url=None
            )
        assert len(calls) == 1
    finally:
        await adapter.aclose()


async def test_imessage_uses_a_real_tapback_and_the_exact_verified_message() -> None:
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": 200, "message": "Success"})

    adapter = ImessageAdapter(httpx.MockTransport(respond))
    try:
        await adapter.react_to_message(
            credential().encode(), "iMessage;+;chat123", "MESSAGE-GUID", "heart", api_base_url=None
        )
        assert json.loads(calls[0].content) == {
            "chatGuid": "iMessage;+;chat123",
            "selectedMessageGuid": "MESSAGE-GUID",
            "reaction": "love",
            "partIndex": 0,
        }
        with pytest.raises(ChannelDirectoryUnsupported):
            await adapter.react_to_message(
                credential().encode(),
                "iMessage;+;chat123",
                "MESSAGE-GUID",
                "unknown",
                api_base_url=None,
            )
        assert len(calls) == 1
    finally:
        await adapter.aclose()
