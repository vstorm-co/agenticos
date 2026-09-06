"""Opening and closing a bot's inbound stream while the deployment runs.

The adapters are singletons and are told a self-hosted bot's server address and
a Slack app's own token *before* the connection opens. That ordering used to be
written out in the lifespan and nowhere else, so it could only ever be got right
once - and everything else that wanted a stream had to be a restart.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.slack import SlackAdapter
from app.services.channels.supervisor import (
    allow_intake,
    begin_shutdown,
    close_inbound_stream,
    open_inbound_stream,
)
from app.services.channels.telegram import TelegramAdapter

pytestmark = pytest.mark.anyio


def _adapter(**extra) -> MagicMock:
    adapter = MagicMock(start_polling=AsyncMock(), stop_polling=AsyncMock(), **extra)
    return adapter


class TestOpening:
    async def test_the_bot_is_told_what_it_needs_before_the_socket_opens(self):
        """An adapter is one object serving every bot, so a per-bot fact - the
        Mattermost server address, a Slack app's token - has to be registered
        against the id first: a stream opened before it has nowhere to connect."""
        order: list[str] = []
        adapter = _adapter(
            prepare_connection=MagicMock(side_effect=lambda *_, **__: order.append("prepare")),
        )
        adapter.start_polling = AsyncMock(side_effect=lambda *_: order.append("start"))

        with patch("app.services.channels.supervisor.get_adapter", return_value=adapter):
            await open_inbound_stream(
                bot_id="b-1",
                platform="mattermost",
                token="tok",
                api_base_url="https://mattermost.acme.com",
                app_token="xapp",
            )

        assert order == ["prepare", "start"]
        adapter.prepare_connection.assert_called_once_with(
            "b-1", api_base_url="https://mattermost.acme.com", app_token="xapp"
        )

    async def test_an_existing_stream_is_closed_first(self):
        """`start_polling` returns early when a task for that bot is running, so
        without this a bot whose token or server just changed would keep talking
        with the old one - which is the case somebody edits a bot to fix."""
        order: list[str] = []
        adapter = _adapter()
        adapter.stop_polling = AsyncMock(side_effect=lambda *_: order.append("stop"))
        adapter.start_polling = AsyncMock(side_effect=lambda *_: order.append("start"))

        with patch("app.services.channels.supervisor.get_adapter", return_value=adapter):
            await open_inbound_stream(bot_id="b-1", platform="telegram", token="tok")

        assert order == ["stop", "start"]


class TestWhatEachAdapterPrepares:
    """The hook is on the base, so every adapter is asked the same way; what
    each one keeps is its own. The `getattr` reach this replaced needed the
    supervisor to know the two method names, and a third adapter would have been
    a third name."""

    def test_mattermost_keeps_the_server_and_ignores_the_app_token(self):
        adapter = MattermostAdapter()

        adapter.prepare_connection("b-1", api_base_url="https://mm.acme.com/", app_token="xapp")

        assert adapter._base_urls == {"b-1": "https://mm.acme.com"}

    def test_slack_keeps_the_app_token_and_ignores_the_server(self):
        adapter = SlackAdapter()

        adapter.prepare_connection("b-1", api_base_url="https://mm.acme.com", app_token="xapp")

        assert adapter._app_tokens == {"b-1": "xapp"}

    def test_a_platform_that_needs_neither_keeps_nothing(self):
        adapter = TelegramAdapter()

        adapter.prepare_connection("b-1", api_base_url="https://mm.acme.com", app_token="xapp")

        assert not hasattr(adapter, "_base_urls")

    def test_nothing_is_kept_for_a_bot_that_supplied_nothing(self):
        mattermost, slack = MattermostAdapter(), SlackAdapter()

        mattermost.prepare_connection("b-1", api_base_url=None, app_token=None)
        slack.prepare_connection("b-1", api_base_url=None, app_token=None)

        assert mattermost._base_urls == {}
        assert slack._app_tokens == {}


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


class TestShutdown:
    """A stream deferred just before shutdown must not reopen intake at exit (#1119).

    The `_shutting_down` flag is a process global; `tests/conftest.py` resets it
    after every test, so a `begin_shutdown()` here does not leak.
    """

    async def test_a_late_open_declines_to_reopen_intake_while_shutting_down(self):
        begin_shutdown()
        adapter = _adapter()
        with patch("app.services.channels.supervisor.get_adapter", return_value=adapter) as get:
            await open_inbound_stream(bot_id="b-1", platform="telegram", token="tok")

        get.assert_not_called()
        adapter.start_polling.assert_not_awaited()

    async def test_a_shutdown_during_stop_polling_still_declines_to_reopen(self):
        """The flag can flip while the open is suspended at stop_polling, so it is
        re-checked before start_polling - a task parked there does not reopen."""
        adapter = _adapter()
        adapter.stop_polling = AsyncMock(side_effect=lambda *_: begin_shutdown())
        with patch("app.services.channels.supervisor.get_adapter", return_value=adapter):
            await open_inbound_stream(bot_id="b-1", platform="telegram", token="tok")

        adapter.start_polling.assert_not_awaited()

    async def test_intake_reopens_once_a_fresh_lifespan_permits_it(self):
        begin_shutdown()
        allow_intake()
        adapter = _adapter()
        with patch("app.services.channels.supervisor.get_adapter", return_value=adapter):
            await open_inbound_stream(bot_id="b-1", platform="telegram", token="tok")

        adapter.start_polling.assert_awaited_once()
