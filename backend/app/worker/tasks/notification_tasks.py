"""Sends what the notification write path queued (#1598).

One flow, two committed steps: claim due deliveries and advance their lease
(one transaction), then send and settle each claimed row (one transaction
apiece, opened fresh per row - see `app.services.notification_delivery` for
why holding one session across both would undo the claim's own guarantee).
A final, claim-free step reaps any row a dead worker left exhausted with no
recorded outcome.
"""

import logging
from collections import Counter
from datetime import UTC, datetime
from uuid import UUID

from prefect import flow

from app.db.session import get_worker_db_context
from app.services.notification_delivery import NotificationDeliveryService

logger = logging.getLogger(__name__)


async def _send_and_settle_one(delivery_id: UUID, *, claimed_at: datetime) -> str:
    """Its own session, its own transaction - the second half of the claimed
    row's two-transaction shape, opened fresh per row rather than reusing the
    claim's session."""
    async with get_worker_db_context() as db:
        return await NotificationDeliveryService(db).send_and_settle(
            delivery_id, claimed_at=claimed_at
        )


@flow(name="notification-delivery-sweep")
async def notification_delivery_sweep_flow() -> dict[str, int]:
    """Claim, send and settle every due delivery, then reap what a dead
    worker left behind. Returns outcome counts, so a flow run's result says
    what it did without anybody reading the logs."""
    now = datetime.now(UTC)
    async with get_worker_db_context() as db:
        claimed = await NotificationDeliveryService(db).claim_and_advance(now=now)

    outcomes: Counter[str] = Counter()
    for delivery in claimed:
        # `claimed_at` is nullable on the model in general (a never-claimed
        # row), but `claim_and_advance` just stamped it on every row it
        # returned.
        assert delivery.claimed_at is not None
        outcome = await _send_and_settle_one(delivery.id, claimed_at=delivery.claimed_at)
        outcomes[outcome] += 1

    async with get_worker_db_context() as db:
        reaped = await NotificationDeliveryService(db).reap_exhausted(now=now)

    counts = {
        "sent": outcomes["sent"],
        "skipped": outcomes["skipped"],
        "failed": outcomes["failed"],
        "lost_claim": outcomes["lost_claim"],
        "reaped": reaped,
    }
    if counts["failed"] or counts["reaped"]:
        logger.warning("Notification delivery sweep: %s", counts)
    return counts
