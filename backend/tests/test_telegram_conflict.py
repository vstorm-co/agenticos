"""Two pollers on one Telegram token stop fighting (#2224).

On 2026-10-18 prod logged 154 `TelegramConflictError`s in fifteen minutes: two
processes polled one bot, and aiogram, which catches every poll error and polls
again, let them end each other's requests for as long as both ran. The adapter
now hears the conflict through a request middleware on the polling bot, and
either closes its own copy - when another worker holds the stream lease - or,
when it is the holder, says on the channels listing what is in its way.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramConflictError
from aiogram.methods import GetMe, GetUpdates

from app.services.channels.telegram import ANOTHER_POLLER, TelegramAdapter, _ConflictWatch

pytestmark = pytest.mark.anyio

MODULE = "app.services.channels.telegram"


def _conflict(method: object) -> TelegramConflictError:
    return TelegramConflictError(
        method=method,  # ty: ignore[invalid-argument-type]
        message="Conflict: terminated by other getUpdates request",
    )


class TestTheWatch:
    async def test_a_poll_ended_by_another_is_reported_and_still_raised(self) -> None:
        """Still raised: aiogram's own backoff is what the poll returns to."""
        heard = AsyncMock()
        polling = GetUpdates(timeout=10)
        make_request = AsyncMock(side_effect=_conflict(polling))

        with pytest.raises(TelegramConflictError):
            await _ConflictWatch(heard, AsyncMock())(make_request, MagicMock(), polling)

        heard.assert_awaited_once_with()

    async def test_a_conflict_on_any_other_call_is_not_a_second_poller(self) -> None:
        heard = AsyncMock()
        call = GetMe()

        with pytest.raises(TelegramConflictError):
            await _ConflictWatch(heard, AsyncMock())(
                AsyncMock(side_effect=_conflict(call)), MagicMock(), call
            )

        heard.assert_not_awaited()

    async def test_a_successful_call_passes_through(self) -> None:
        heard = AsyncMock()
        make_request = AsyncMock(return_value="updates")

        answer = await _ConflictWatch(heard, AsyncMock())(make_request, MagicMock(), GetUpdates())

        assert answer == "updates"
        heard.assert_not_awaited()


class TestTheRecovery:
    """#2252: the poll after a conflict clears is what says the bot is back."""

    async def test_the_first_poll_that_succeeds_after_a_conflict_records_up(self) -> None:
        heard, recovered = AsyncMock(), AsyncMock()
        watch = _ConflictWatch(heard, recovered)
        polling = GetUpdates(timeout=10)

        with pytest.raises(TelegramConflictError):
            await watch(AsyncMock(side_effect=_conflict(polling)), MagicMock(), polling)
        assert watch.conflicted

        await watch(AsyncMock(return_value=[]), MagicMock(), polling)
        await watch(AsyncMock(return_value=[]), MagicMock(), polling)

        recovered.assert_awaited_once_with()
        assert not watch.conflicted

    async def test_another_call_succeeding_mid_conflict_is_not_a_recovery(self) -> None:
        """A reply sent while the other poller still holds the bot says nothing about polling."""
        recovered = AsyncMock()
        watch = _ConflictWatch(AsyncMock(), recovered)
        polling = GetUpdates()
        with pytest.raises(TelegramConflictError):
            await watch(AsyncMock(side_effect=_conflict(polling)), MagicMock(), polling)

        await watch(AsyncMock(return_value="me"), MagicMock(), GetMe())

        recovered.assert_not_awaited()
        assert watch.conflicted


class TestWhatTheAdapterDoes:
    async def test_the_copy_without_the_lease_closes_itself(self) -> None:
        adapter = TelegramAdapter()
        poll = asyncio.create_task(asyncio.sleep(3600))
        adapter._polling_tasks["bot"] = poll
        leases = MagicMock(holds=AsyncMock(return_value=False), holder="worker-b")

        with (
            patch(f"{MODULE}.stream_lease.leases", return_value=leases),
            patch(f"{MODULE}.connection_state.record_down", new=AsyncMock()) as record_down,
        ):
            await adapter._another_poller("bot")

        leases.drop.assert_called_once_with("bot")
        assert "bot" not in adapter._polling_tasks
        with pytest.raises(asyncio.CancelledError):
            await poll
        # The holder is serving the bot; this copy closing is not an outage.
        record_down.assert_not_awaited()

    async def test_the_holder_keeps_polling_and_names_the_intruder(self) -> None:
        adapter = TelegramAdapter()
        poll = asyncio.create_task(asyncio.sleep(3600))
        adapter._polling_tasks["bot"] = poll
        leases = MagicMock(holds=AsyncMock(return_value=True), holder="worker-a")

        with (
            patch(f"{MODULE}.stream_lease.leases", return_value=leases),
            patch(f"{MODULE}.connection_state.record_down", new=AsyncMock()) as record_down,
        ):
            await adapter._another_poller("bot")

        record_down.assert_awaited_once_with("bot", ANOTHER_POLLER)
        leases.drop.assert_not_called()
        assert adapter._polling_tasks["bot"] is poll
        assert not poll.done()
        poll.cancel()
