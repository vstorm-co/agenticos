"""One reconnect loop for every inbound stream, and what it must do.

Each adapter used to carry a loop of its own, and the three disagreed. Two put
the sleep inside `except Exception`, so a session that ended by returning
without ever awaiting - a Slack bot with no `xapp-` token, a Mattermost bot with
no server URL, either package missing - was retried without yielding: the loop
ran at 100% CPU and **nothing else on the process was scheduled again**, the
health check included. Two knew a configuration error from a crash and stopped;
Telegram did not, so a bot with a rejected token was retried for ever, a
traceback every five seconds. One backed off; two retried every five seconds
flat.

`supervise_stream` in `base.py` is the one loop now, and these tests hold it to
one contract through all three adapters: it suspends between sessions whatever
the session does, it stops on `ChannelNotConfigured` after recording `down`
once, and it backs off on a crash and resets after a clean session.

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
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramUnauthorizedError

from app.services.channels import base as base_module
from app.services.channels import mattermost as mattermost_module
from app.services.channels import slack as slack_module
from app.services.channels import telegram as telegram_module
from app.services.channels.base import supervise_stream
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.slack import SlackAdapter
from app.services.channels.telegram import TelegramAdapter

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


async def _stops_after_one_attempt(
    monkeypatch: pytest.MonkeyPatch,
    adapter: Any,
    session_attr: str,
    supervisor: Callable[[], Awaitable[None]],
) -> tuple[int, AsyncMock]:
    """Run the supervisor over a session that cannot be configured; count attempts
    and hand back what the connection row was told."""
    attempts = 0

    async def session(*_: object, **__: object) -> None:
        nonlocal attempts
        attempts += 1
        raise ChannelNotConfigured(message="the operator has not filled this in")

    recorded = AsyncMock()
    monkeypatch.setattr(adapter, session_attr, session)
    monkeypatch.setattr(base_module.connection_state, "record_down", recorded)
    await supervisor()
    return attempts, recorded


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

        attempts, recorded = await _stops_after_one_attempt(
            monkeypatch,
            adapter,
            "_run_socket_mode",
            lambda: adapter._socket_supervisor("bot", "xoxb-token"),
        )

        assert attempts == 1
        recorded.assert_awaited_once_with("bot", "the operator has not filled this in")

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

        attempts, recorded = await _stops_after_one_attempt(
            monkeypatch,
            adapter,
            "_run_stream",
            lambda: adapter._supervise("bot", "token"),
        )

        assert attempts == 1
        recorded.assert_awaited_once()

    async def test_the_missing_server_url_raises_rather_than_returning(self) -> None:
        """And the refusal is what the connection row will show, so it names the
        way out: the server URL, or webhook mode, which needs no stream."""
        adapter = MattermostAdapter()

        with pytest.raises(ChannelNotConfigured) as refused:
            await adapter._run_stream("bot-without-a-url", "token")

        assert "webhook mode" in refused.value.message


class TestTelegram:
    async def test_a_session_that_returns_immediately_still_sleeps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adapter = TelegramAdapter()

        sleeps = await _sleeps_between_sessions(
            monkeypatch,
            telegram_module,
            adapter,
            "_run_polling_once",
            lambda: adapter._polling_supervisor("bot", "123:token"),
        )

        assert sleeps == 2

    async def test_a_telegram_config_error_records_down_and_stops_rather_than_looping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one adapter whose loop had no such branch: a bot with a bad token
        was retried every five seconds for the life of the process, re-recording
        `down` each time, where the other two record it once and stop."""
        adapter = TelegramAdapter()

        attempts, recorded = await _stops_after_one_attempt(
            monkeypatch,
            adapter,
            "_run_polling_once",
            lambda: adapter._polling_supervisor("bot", "123:token"),
        )

        assert attempts == 1
        recorded.assert_awaited_once_with("bot", "the operator has not filled this in")

    async def test_a_rejected_token_is_a_configuration_error_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Where the distinction is made for Telegram: aiogram answers a bad token
        with its 401, and left as that it is a crash the loop retries. Nothing a
        retry does will make the token valid."""
        adapter = TelegramAdapter()
        dispatcher = MagicMock()
        dispatcher.start_polling = AsyncMock(
            side_effect=TelegramUnauthorizedError(method=MagicMock(), message="Unauthorized")
        )

        @contextlib.asynccontextmanager
        async def fake_bot(*_: object, **__: object):
            yield MagicMock()

        monkeypatch.setattr(TelegramAdapter, "_bot", staticmethod(fake_bot))
        monkeypatch.setattr(telegram_module, "Dispatcher", MagicMock(return_value=dispatcher))
        monkeypatch.setattr(telegram_module.connection_state, "record_up", AsyncMock())

        with pytest.raises(ChannelNotConfigured) as refused:
            await adapter._run_polling_once("bot", "123:bad-token")

        assert "token" in refused.value.message


class TestTheOneLoop:
    async def test_all_three_adapters_run_the_same_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A reconnect fix that lands in one place lands in all three."""
        shared = AsyncMock()
        for module in (slack_module, telegram_module, mattermost_module):
            monkeypatch.setattr(module, "supervise_stream", shared)

        await SlackAdapter()._socket_supervisor("bot", "xoxb")
        await TelegramAdapter()._polling_supervisor("bot", "123:t")
        await MattermostAdapter()._supervise("bot", "t")

        assert shared.await_count == 3
        platforms = {call.kwargs["platform"] for call in shared.await_args_list}
        assert platforms == {"Slack Socket Mode", "Telegram polling", "Mattermost event stream"}

    async def test_a_crash_backs_off_and_a_clean_session_resets_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The log names `delay`, so `delay` has to be what is then slept -
        doubling after the wait keeps the two agreeing and the first retry
        prompt. A session that ended cleanly starts the ladder over."""
        outcomes: list[BaseException | None] = [
            RuntimeError("dropped"),
            RuntimeError("dropped"),
            RuntimeError("dropped"),
            None,
            RuntimeError("dropped"),
            asyncio.CancelledError(),
        ]
        waited: list[float] = []
        recorded = AsyncMock()

        async def session() -> None:
            outcome = outcomes.pop(0)
            if outcome is not None:
                raise outcome

        async def counting_sleep(delay: float) -> None:
            waited.append(delay)

        monkeypatch.setattr(base_module.asyncio, "sleep", counting_sleep)
        monkeypatch.setattr(base_module.connection_state, "record_down", recorded)

        with contextlib.suppress(asyncio.CancelledError):
            await supervise_stream(
                "bot", platform="Test stream", session=session, failing="keeps dropping"
            )

        assert waited == [5.0, 10.0, 20.0, 5.0, 5.0]
        assert recorded.await_count == 4
        recorded.assert_awaited_with("bot", "keeps dropping")

    async def test_the_wait_is_capped_at_a_minute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        crashes = 8
        waited: list[float] = []

        async def session() -> None:
            nonlocal crashes
            crashes -= 1
            if crashes < 0:
                raise asyncio.CancelledError
            raise RuntimeError("dropped")

        async def counting_sleep(delay: float) -> None:
            waited.append(delay)

        monkeypatch.setattr(base_module.asyncio, "sleep", counting_sleep)
        monkeypatch.setattr(base_module.connection_state, "record_down", AsyncMock())

        with contextlib.suppress(asyncio.CancelledError):
            await supervise_stream("bot", platform="Test stream", session=session, failing="x")

        assert waited == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0, 60.0, 60.0]

    async def test_a_cancelled_session_ends_the_loop_cancelled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`stop_polling` cancels the task and awaits it; swallowing the
        cancellation would report a stream as stopped while its loop went on."""

        async def session() -> None:
            raise asyncio.CancelledError

        monkeypatch.setattr(base_module.connection_state, "record_down", AsyncMock())

        with pytest.raises(asyncio.CancelledError):
            await supervise_stream("bot", platform="Test stream", session=session, failing="x")
