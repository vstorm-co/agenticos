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
than a channel message id, and does not need the channel path's release-on-failure
because the delivery is only claimed once the fire has been handed off (the route
gives the claim back if that hand-off fails).
"""

from __future__ import annotations

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

    Called by the lifespan next to the channel dedupe's own `configure`. The
    fire runs outside any request - a dispatched Prefect flow - so the claim
    cannot reach Redis through `request.state` and is handed the shared client
    here instead.
    """
    global _redis
    _redis = redis


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
    """Give a claim back, so a redelivery of a fire that was never dispatched is
    processed rather than mistaken for one that was.

    The claim is taken before the fire is handed to the worker. If that hand-off
    raises - Prefect unreachable - the provider gets no 2xx and will resend; the
    claim must not outlive the failed attempt, or the resend is dropped and the
    event is lost. Best effort, on the same reasoning as the claim: a claim that
    cannot be given back costs one duplicate fire, where raising here would replace
    the failure the caller is already handling with this one.
    """
    if _redis is None:
        return
    try:
        await _redis.delete(_key(trigger_id, delivery_id))
    except Exception:
        logger.warning("trigger_dedupe_release_failed", exc_info=True)
