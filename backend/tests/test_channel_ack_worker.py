"""An admitted acknowledgement must not depend on the process owning the stream."""

import json
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest

from app.db.models.channel_bot import ChannelBot
from app.services.channels.base import IncomingMessage
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.router import ChannelMessageRouter

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("stale_cache", [False, True])
async def test_mattermost_worker_ack_uses_current_bot_connection_without_a_stream(
    stale_cache: bool,
) -> None:
    bot_id = uuid4()
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/v4/users/me":
            return httpx.Response(200, json={"id": "current-bot", "username": "agent"})
        return httpx.Response(201, json={})

    adapter = MattermostAdapter()
    await adapter.aclose()
    if stale_cache:
        adapter.remember_server(str(bot_id), "https://old.example.com")
        adapter._own_ids[str(bot_id)] = "stale-bot"
    bot = ChannelBot(
        id=bot_id,
        organization_id=uuid4(),
        platform="mattermost",
        api_base_url="https://mattermost.example.com/",
        ack_reaction="writing_hand",
    )
    incoming = IncomingMessage(
        platform="mattermost",
        bot_id=str(bot_id),
        platform_user_id="person",
        platform_chat_id="channel:post",
        chat_type="group",
        text="Hello",
        message_id="post",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter._http = client
        with (
            patch("app.services.channels.router.get_adapter", return_value=adapter),
            patch("app.services.channels.router.unseal_bot_token", return_value="fixture-token"),
        ):
            await ChannelMessageRouter()._acknowledge(bot, incoming)
    assert [(request.method, str(request.url)) for request in calls] == [
        ("GET", "https://mattermost.example.com/api/v4/users/me"),
        ("POST", "https://mattermost.example.com/api/v4/reactions"),
    ]
    assert json.loads(calls[-1].content) == {
        "user_id": "current-bot",
        "post_id": "post",
        "emoji_name": "writing_hand",
    }
    assert all(request.headers["authorization"] == "Bearer fixture-token" for request in calls)
