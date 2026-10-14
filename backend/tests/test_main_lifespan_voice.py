"""Shutdown hangs up this worker's voice calls before it drains background work (#54)."""

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.anyio


async def test_shutdown_ends_live_calls_before_draining_background_work():
    order: list[str] = []
    with (
        patch(
            "app.main.LIVE_CALLS.end_all",
            AsyncMock(side_effect=lambda **kw: order.append("calls") or 0),
        ),
        patch(
            "app.main.background.drain",
            AsyncMock(side_effect=lambda *a, **kw: order.append("drain")),
        ),
    ):
        from app.main import _shutdown_voice_then_drain

        await _shutdown_voice_then_drain()
    assert order == ["calls", "drain"]


async def test_a_worker_reaps_what_its_previous_life_left_on_start():
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from app.main import _reap_voice_calls

    session = MagicMock()

    @asynccontextmanager
    async def context():
        yield session

    with (
        patch("app.main.get_db_context", context),
        patch("app.main.VoiceCallReaper") as reaper_cls,
    ):
        reaper_cls.return_value.reap = AsyncMock(return_value=2)
        await _reap_voice_calls()

    assert reaper_cls.call_args.args == (session,)
    reaper_cls.return_value.reap.assert_awaited_once()
