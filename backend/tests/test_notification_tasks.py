"""The sweep flow itself: three steps, three sessions, one summary (#1598).

`NotificationDeliveryService`'s own tests (`tests/integration/
test_notification_delivery.py`) prove the claim, the send, the settle and the
reap each do the right thing against a real database. What is left here is
the flow's own shape: that it opens a session per step rather than one shared
across all of them - the reason the claim's own guarantee survives a crash
mid-send - and that its outcome counts add up. Modelled on
`tests/test_run_reaper.py`'s `TestTheFlow`: the `@flow`-decorated function is
awaited directly, with `get_worker_db_context` and the service it opens
patched, never through Prefect's own machinery.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.tasks.notification_tasks import _CONCURRENT_SENDS, notification_delivery_sweep_flow

MODULE = "app.worker.tasks.notification_tasks"


def _worker_db_context() -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _delivery(*, claimed_at: datetime) -> MagicMock:
    delivery = MagicMock()
    delivery.id = uuid.uuid4()
    delivery.claimed_at = claimed_at
    return delivery


pytestmark = pytest.mark.anyio


class TestTheFlow:
    async def test_every_claimed_row_is_sent_in_its_own_session(self):
        now = datetime.now(UTC)
        claimed = [_delivery(claimed_at=now), _delivery(claimed_at=now)]
        service = MagicMock(
            claim_and_advance=AsyncMock(return_value=claimed),
            reap_exhausted=AsyncMock(return_value=0),
            send_and_settle=AsyncMock(return_value="sent"),
        )
        contexts = [_worker_db_context() for _ in range(4)]  # claim, 2 sends, reap

        with (
            patch(f"{MODULE}.get_worker_db_context", side_effect=contexts),
            patch(f"{MODULE}.NotificationDeliveryService", return_value=service),
        ):
            counts = await notification_delivery_sweep_flow()

        assert counts == {"sent": 2, "skipped": 0, "failed": 0, "lost_claim": 0, "reaped": 0}
        assert service.send_and_settle.await_count == 2

    async def test_outcomes_of_every_kind_are_all_counted(self):
        now = datetime.now(UTC)
        claimed = [_delivery(claimed_at=now) for _ in range(4)]
        service = MagicMock(
            claim_and_advance=AsyncMock(return_value=claimed),
            reap_exhausted=AsyncMock(return_value=1),
            send_and_settle=AsyncMock(side_effect=["sent", "skipped", "failed", "lost_claim"]),
        )
        contexts = [_worker_db_context() for _ in range(6)]

        with (
            patch(f"{MODULE}.get_worker_db_context", side_effect=contexts),
            patch(f"{MODULE}.NotificationDeliveryService", return_value=service),
        ):
            counts = await notification_delivery_sweep_flow()

        assert counts == {"sent": 1, "skipped": 1, "failed": 1, "lost_claim": 1, "reaped": 1}

    async def test_sends_overlap_up_to_the_bound_not_the_whole_batch(self):
        """The reason for `asyncio.gather` over the old sequential loop: a
        batch bigger than the two-minute lease could survive one row at a
        time still finishes inside it once sends overlap. Proven by never
        letting more than `_CONCURRENT_SENDS` run at once, and by that bound
        actually being reached rather than sends still queueing behind each
        other one at a time."""
        now = datetime.now(UTC)
        batch_size = _CONCURRENT_SENDS * 2 + 5
        claimed = [_delivery(claimed_at=now) for _ in range(batch_size)]
        in_flight = 0
        max_in_flight = 0

        async def _concurrent_send(delivery_id, *, claimed_at):
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0)  # cede control, so overlap is observable
            in_flight -= 1
            return "sent"

        service = MagicMock(
            claim_and_advance=AsyncMock(return_value=claimed),
            reap_exhausted=AsyncMock(return_value=0),
            send_and_settle=AsyncMock(side_effect=_concurrent_send),
        )
        contexts = [_worker_db_context() for _ in range(batch_size + 2)]

        with (
            patch(f"{MODULE}.get_worker_db_context", side_effect=contexts),
            patch(f"{MODULE}.NotificationDeliveryService", return_value=service),
        ):
            counts = await notification_delivery_sweep_flow()

        assert counts["sent"] == batch_size
        assert max_in_flight == _CONCURRENT_SENDS

    async def test_an_empty_sweep_still_reaps(self):
        service = MagicMock(
            claim_and_advance=AsyncMock(return_value=[]),
            reap_exhausted=AsyncMock(return_value=0),
        )
        contexts = [_worker_db_context() for _ in range(2)]  # claim, reap - no sends

        with (
            patch(f"{MODULE}.get_worker_db_context", side_effect=contexts),
            patch(f"{MODULE}.NotificationDeliveryService", return_value=service),
        ):
            counts = await notification_delivery_sweep_flow()

        assert counts == {"sent": 0, "skipped": 0, "failed": 0, "lost_claim": 0, "reaped": 0}
