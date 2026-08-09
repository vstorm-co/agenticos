"""Opening and closing a bot's inbound stream while the deployment runs.

The adapters are singletons and are told a self-hosted bot's server address and
a Slack app's own token *before* the connection opens. That ordering used to be
written out in the lifespan and nowhere else, so it could only ever be got right
once - and everything else that wanted a stream had to be a restart.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.channels.supervisor import close_inbound_stream, open_inbound_stream

pytestmark = pytest.mark.anyio


def _adapter(**extra) -> MagicMock:
    adapter = MagicMock(start_polling=AsyncMock(), stop_polling=AsyncMock(), **extra)
    return adapter


class TestOpening:
    async def test_the_bot_is_told_its_own_server_before_the_socket_opens(self):
        """A Mattermost adapter is one object serving every bot, so the address
        has to be registered against the id first - a stream opened before it
        has nowhere to connect."""
        order: list[str] = []
        adapter = _adapter(
            remember_server=MagicMock(side_effect=lambda *_: order.append("remember")),
        )
        adapter.start_polling = AsyncMock(side_effect=lambda *_: order.append("start"))
        del adapter.remember_app_token

        with patch("app.services.channels.supervisor.get_adapter", return_value=adapter):
            await open_inbound_stream(
                bot_id="b-1",
                platform="mattermost",
                token="tok",
                api_base_url="https://mattermost.acme.com",
            )

        assert order == ["remember", "start"]
        adapter.remember_server.assert_called_once_with("b-1", "https://mattermost.acme.com")

    async def test_a_slack_app_token_is_registered_the_same_way(self):
        adapter = _adapter(remember_app_token=MagicMock())
        del adapter.remember_server

        with patch("app.services.channels.supervisor.get_adapter", return_value=adapter):
            await open_inbound_stream(
                bot_id="b-1", platform="slack", token="xoxb", app_token="xapp"
            )

        adapter.remember_app_token.assert_called_once_with("b-1", "xapp")

    async def test_an_existing_stream_is_closed_first(self):
        """`start_polling` returns early when a task for that bot is running, so
        without this a bot whose token or server just changed would keep talking
        with the old one - which is the case somebody edits a bot to fix."""
        order: list[str] = []
        adapter = _adapter()
        adapter.stop_polling = AsyncMock(side_effect=lambda *_: order.append("stop"))
        adapter.start_polling = AsyncMock(side_effect=lambda *_: order.append("start"))
        del adapter.remember_server
        del adapter.remember_app_token

        with patch("app.services.channels.supervisor.get_adapter", return_value=adapter):
            await open_inbound_stream(bot_id="b-1", platform="telegram", token="tok")

        assert order == ["stop", "start"]

    async def test_a_platform_with_no_address_is_not_told_one(self):
        adapter = _adapter(remember_server=MagicMock())
        del adapter.remember_app_token

        with patch("app.services.channels.supervisor.get_adapter", return_value=adapter):
            await open_inbound_stream(bot_id="b-1", platform="telegram", token="tok")

        adapter.remember_server.assert_not_called()


class TestClosing:
    async def test_the_stream_is_stopped(self):
        adapter = _adapter()

        with patch("app.services.channels.supervisor.get_adapter", return_value=adapter):
            await close_inbound_stream(bot_id="b-1", platform="telegram")

        adapter.stop_polling.assert_awaited_once_with("b-1")

    async def test_a_platform_with_no_adapter_is_logged_rather_than_raised_at(self):
        """This runs after a transaction committed. Raising would leave a bot
        deleted and a background task failing about it."""
        with patch("app.services.channels.supervisor.get_adapter", side_effect=KeyError("discord")):
            await close_inbound_stream(bot_id="b-1", platform="discord")
