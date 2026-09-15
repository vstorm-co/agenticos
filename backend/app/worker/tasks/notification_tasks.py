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
from datetime import UTC, datetime, timedelta
from uuid import UUID

from prefect import flow

from app.db.models.notification import (
    NOTIFICATION_OUTER_RETENTION_DAYS,
    NOTIFICATION_READ_RETENTION_DAYS,
)
from app.db.session import get_worker_db_context
from app.repositories import notification_repo
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


@flow(name="notification-retention-sweep", log_prints=True)
async def notification_retention_sweep_flow() -> int:
    """Drop notifications past their retention window (Decision 8).

    A read notification is dropped once it has sat around, read, for
    `NOTIFICATION_READ_RETENTION_DAYS` - nobody is coming back to a read
    inbox item ninety days later. An unread one gets the benefit of the
    doubt until `NOTIFICATION_OUTER_RETENTION_DAYS`, so it does not vanish
    out from under someone who genuinely has not looked, but even that
    grace has a ceiling: a row that old is dropped either way. Daily,
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
