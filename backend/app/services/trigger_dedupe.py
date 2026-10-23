"""Once-only claim on an inbound event-trigger delivery.

Webhook providers deliver at-least-once. A 202 lost on the wire - a proxy drops
it, the pod is rotated between dispatching the fire and flushing the socket - was
never received by the provider, and the redelivery that follows is a valid, signed,
brand-new request carrying the same event. An ordinary provider retry is the same
shape. Without a claim, every such redelivery is a second agent run: a second model
call and a second spend against the organization's budget for one event (Codex P1,
#537).

The claim is one atomic `SET NX` against the deployment's shared Redis, keyed on
the provider's own delivery id - the id a provider reuses when it re-sends, so the
retry lands on the same key. It is the same mechanism the channel webhooks use
(:mod:`app.services.channels.dedupe`); a trigger keys on the delivery id rather
than a channel message id.

The claim is taken before the fire is queued, and the fire is a job row in the
same transaction - so a transaction that rolls back has queued nothing, and its
claim is released (`release_event_delivery`, through `spawn_after_rollback`).
Kept, it would answer the provider's retry as a duplicate for fifteen minutes,
the provider would stop retrying, and the event would be lost. Under Prefect the
release was deliberately absent: a dispatch that raised might have reached the
server anyway, so a failure said nothing about whether the fire existed.
"""

import logging
from uuid import UUID

from app.clients.redis import RedisClient

logger = logging.getLogger(__name__)

SEEN_TTL_SECONDS = 15 * 60
"""How long a claim outlives its delivery.

Long enough to cover a provider's redelivery window and short enough that the
keyspace stays proportional to recent traffic rather than to history - the same
reasoning, and the same value, as the channel dedupe.
"""

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`.

    Called by the lifespan next to the channel dedupe's own `configure`. A polled
    portal's fire is decided outside any request - in a worker job - so the claim
    cannot reach Redis through `request.state` and is handed the shared client
    here instead.
    """
    global _redis
    _redis = redis


def is_configured() -> bool:
    """Whether a Redis was handed over - what a non-API process checks before
    claiming, since only the API lifespan configures this module and a claim
    with no Redis fails open into exactly the duplicate it exists to stop."""
    return _redis is not None


def _key(trigger_id: UUID, delivery_id: str) -> str:
    return f"trigger:seen:{trigger_id}:{delivery_id}"


async def claim_event_delivery(*, trigger_id: UUID, delivery_id: str) -> bool:
    """Claim this delivery. `True` means it is ours to fire; `False` means an
    earlier delivery of the same event already was.

    Fails open, with a log line: a module nothing configured and a Redis that
    cannot be reached both answer `True`. Dropping a real event is a worse
    failure than firing a redelivered one twice - the duplicate is the rarer event
    and costs money, the drop is an automation that silently did not run - so
    degrading loses the guarantee, never the event. A delivery whose provider sent
    no id never reaches here: the caller does not claim one it cannot key.
    """
    if _redis is None:
        logger.warning("trigger_dedupe_not_configured", extra={"trigger_id": str(trigger_id)})
        return True
    try:
        return await _redis.set(_key(trigger_id, delivery_id), "1", ttl=SEEN_TTL_SECONDS, nx=True)
    except Exception:
        logger.warning("trigger_dedupe_redis_unavailable", exc_info=True)
        return True


async def release_event_delivery(*, trigger_id: UUID, delivery_id: str) -> None:
    """Give a claim back, because the transaction that queued its fire rolled back.

    Unconditional: the only other writer of this key is another delivery of the
    same event, and releasing its claim lets at most one more retry fire - the
    direction `claim_event_delivery` already fails in. A Redis that cannot be
    reached leaves the claim to lapse with its TTL, logged.
    """
    if _redis is None:
        return
    try:
        await _redis.delete(_key(trigger_id, delivery_id))
    except Exception:
        logger.warning("trigger_dedupe_release_failed", exc_info=True)
