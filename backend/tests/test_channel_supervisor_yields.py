"""A channel supervisor must suspend between attempts, whatever its session does.

Both supervisors were `while True: await self._run_x(...)` with the only sleep
inside `except Exception`. Both inner coroutines have branches that return
without ever awaiting - a Slack bot with no `xapp-` token, a Mattermost bot with
no server URL, either package missing - and awaiting a coroutine that never
suspends does not yield to the event loop.

So the loop ran at 100% CPU and **nothing else on the process was scheduled
again**: not a request, not the health check, not a WebSocket stream. The API
was up and answered nothing, and the only clue was one WARNING line. Both
trigger states are ordinary rows an operator has simply not filled in yet.

Asserted by counting sleeps rather than by racing another task. A starved event
loop cannot run a timer either, so a timeout-based test does not fail - it
hangs, and CI reports a job that ran out of wall clock rather than an assertion
naming the defect. Bounding the loop by cancelling from the third session makes
it terminate under both the fixed and the broken implementation, and the sleep
count is then the whole difference: two, or none.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.services.channels import mattermost as mattermost_module
from app.services.channels import slack as slack_module
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.slack import SlackAdapter

pytestmark = pytest.mark.anyio


async def _sleeps_between_sessions(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    adapter: Any,
    session_attr: str,
    supervisor: Callable[[], Awaitable[None]],
) -> int:
    """Run the supervisor for two sessions that end by returning, count sleeps.

    The third session raises `CancelledError`, which is how the loop is bounded
    without depending on the event loop being responsive.
    """
    sessions = 0
    sleeps = 0

    async def session(*_: object, **__: object) -> None:
        nonlocal sessions
        sessions += 1
        if sessions >= 3:
            raise asyncio.CancelledError

    async def counting_sleep(_delay: float) -> None:
        nonlocal sleeps
        sleeps += 1

    monkeypatch.setattr(adapter, session_attr, session)
    monkeypatch.setattr(module.asyncio, "sleep", counting_sleep)

    with contextlib.suppress(asyncio.CancelledError):
        await supervisor()
    return sleeps


class TestSlack:
    async def test_a_session_that_returns_immediately_still_sleeps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = SlackAdapter()

        sleeps = await _sleeps_between_sessions(
            monkeypatch,
            slack_module,
            adapter,
            "_run_socket_mode",
            lambda: adapter._socket_supervisor("bot", "xoxb-token"),
        )

        assert sleeps == 2

    async def test_a_missing_app_token_stops_the_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing a retry can fix - an operator has to paste the xapp- token.
        Retrying is what the spin was."""
        adapter = SlackAdapter()
        attempts = 0

        async def session(*_: object, **__: object) -> None:
            nonlocal attempts
            attempts += 1
            raise ChannelNotConfigured(message="no app token")

        monkeypatch.setattr(adapter, "_run_socket_mode", session)
        await adapter._socket_supervisor("bot", "xoxb-token")

        assert attempts == 1

    async def test_the_missing_app_token_raises_rather_than_returning(self) -> None:
        """Where the distinction is made. Returning here is indistinguishable
        from a session that ended, which is why the supervisor retried it."""
        adapter = SlackAdapter()

        with pytest.raises(ChannelNotConfigured):
            await adapter._run_socket_mode("bot-without-a-token", "xoxb-token")


class TestMattermost:
    async def test_a_session_that_returns_immediately_still_sleeps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = MattermostAdapter()

        sleeps = await _sleeps_between_sessions(
            monkeypatch,
            mattermost_module,
            adapter,
            "_run_stream",
            lambda: adapter._supervise("bot", "token"),
        )

        assert sleeps == 2

    async def test_a_missing_server_url_stops_the_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = MattermostAdapter()
        attempts = 0

        async def session(*_: object, **__: object) -> None:
            nonlocal attempts
            attempts += 1
            raise ChannelNotConfigured(message="no server url")

        monkeypatch.setattr(adapter, "_run_stream", session)
        await adapter._supervise("bot", "token")

        assert attempts == 1

    async def test_the_missing_server_url_raises_rather_than_returning(self) -> None:
        adapter = MattermostAdapter()

        with pytest.raises(ChannelNotConfigured):
            await adapter._run_stream("bot-without-a-url", "token")
