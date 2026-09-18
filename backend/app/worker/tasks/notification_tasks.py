"""Sends what the notification write path queued (#1598).

One flow, two committed steps: claim due deliveries and advance their lease
(one transaction), then send and settle each claimed row (one transaction
apiece, opened fresh per row - see `app.services.notification_delivery` for
why holding one session across both would undo the claim's own guarantee).
A final, claim-free step reaps any row a dead worker left exhausted with no
recorded outcome.
"""

import asyncio
import logging
from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID

from prefect import flow

from app.db.models.notification import (
    NOTIFICATION_OUTER_RETENTION_DAYS,
    NOTIFICATION_READ_RETENTION_DAYS,
)
from app.db.models.notification_delivery import NotificationDelivery
from app.db.session import get_worker_db_context
from app.repositories import notification_repo
from app.services.notification_delivery import NotificationDeliveryService

logger = logging.getLogger(__name__)

# A claimed batch defaults to 30 rows against a two-minute lease
# (`notification_delivery.py`'s `CLAIM_LEASE`) and ten concurrent sends, each
# bounded at `SEND_TIMEOUT_SECONDS` (30s): worst case is three waves of ten,
# ~90s, comfortably inside the 120s lease with margin for the claim and settle
# queries around it. The batch size and the concurrency bound are chosen
# together for exactly this reason - either one raised alone without the
# other reopens the gap: a full batch whose tail is still sending once the
# lease has already expired lets a later sweep reclaim and resend what this
# one has not finished with yet, duplicating the email.
_CONCURRENT_SENDS = 10


def _require_claimed_at(delivery: NotificationDelivery) -> datetime:
    """`claimed_at` is nullable on the model in general (a never-claimed
    row), but `claim_and_advance` just stamped it on every row it returned."""
    assert delivery.claimed_at is not None
    return delivery.claimed_at


async def _send_and_settle_one(
    delivery_id: UUID, *, claimed_at: datetime, semaphore: asyncio.Semaphore
) -> str:
    """Its own session, its own transaction - the second half of the claimed
    row's two-transaction shape, opened fresh per row rather than reusing the
    claim's session."""
    async with semaphore, get_worker_db_context() as db:
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

    semaphore = asyncio.Semaphore(_CONCURRENT_SENDS)
    results = await asyncio.gather(
        *(
            _send_and_settle_one(
                delivery.id, claimed_at=_require_claimed_at(delivery), semaphore=semaphore
            )
            for delivery in claimed
        )
    )
    outcomes: Counter[str] = Counter(results)

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


@flow(name="notification-retention-sweep", log_prints=True)
async def notification_retention_sweep_flow() -> int:
    """Drop notifications past their retention window (Decision 8).

    Both cutoffs are age since the row was *created*, never since it was
    read - see `notification_repo.delete_expired`'s own docstring for why. A
    read notification is dropped once it has existed for
    `NOTIFICATION_READ_RETENTION_DAYS`; nobody is coming back to a read
    inbox item that old. An unread one gets the benefit of the doubt until
    `NOTIFICATION_OUTER_RETENTION_DAYS`, so it does not vanish out from
    under someone who genuinely has not looked, but even that grace has a
    ceiling: a row that old is dropped either way. Daily,
    matching `sweep_sandbox_operations_flow`: the exact hour a row leaves is
    nobody's business, and a delete over a many-day-old boundary is cheap
    run once rather than hourly.
    """
    now = datetime.now(UTC)
    read_cutoff = now - timedelta(days=NOTIFICATION_READ_RETENTION_DAYS)
    outer_cutoff = now - timedelta(days=NOTIFICATION_OUTER_RETENTION_DAYS)
    async with get_worker_db_context() as db:
        removed = await notification_repo.delete_expired(
            db, read_cutoff=read_cutoff, outer_cutoff=outer_cutoff
        )
    logger.info(
        "notification_retention_swept",
        extra={
            "removed": removed,
            "read_retention_days": NOTIFICATION_READ_RETENTION_DAYS,
            "outer_retention_days": NOTIFICATION_OUTER_RETENTION_DAYS,
        },
    )
    return removed
