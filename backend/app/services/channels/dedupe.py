"""Once-only claim on an inbound channel delivery.

Every platform delivers at-least-once. Slack retries an event up to three
times when it sees no 2xx and a Telegram webhook update it got no answer for
is re-sent too, so the fast 200 the webhook routes return prevents only the
slow-handler retry. A 200 lost on the wire - a proxy drops it, the pod is
rotated between scheduling the task and flushing the socket - was never
received, and the redelivery that follows is a valid, signed, brand-new
request carrying the same message. Before this module, every such redelivery
was a full agent run: a second model call, a second spend record and a second
answer in the thread (#167).

The claim is one atomic `SET NX` against the deployment's shared Redis, so
it holds across API workers and covers the pollers as well as the webhook
routes - the router's module-level `_chat_locks` and `_rate_buckets` are
per-process and deliberately no model to follow here. The router takes the
claim at the top of `route`, the one point all six inbound paths cross, and
gives it back if the run under it does not finish.
"""

from __future__ import annotations

import logging

from app.clients.redis import RedisClient
from app.services.channels.base import IncomingMessage

logger = logging.getLogger(__name__)

SEEN_TTL_SECONDS = 15 * 60
"""How long a claim outlives its delivery.

Long enough to cover every platform's redelivery window - Slack's three
retries finish within minutes of the first attempt - and short enough that
the keyspace stays proportional to recent traffic rather than to history.
"""

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`.

    Called by the lifespan next to where the client is created. The module
    does not open a connection of its own: the deduplication guarantee is
    only as wide as the Redis every API worker already shares, and a second
    pool to the same server would be one more thing the shutdown path has to
    know about.
    """
    global _redis
    _redis = redis


def _key(incoming: IncomingMessage) -> str:
    """The claim's address: what the *platform* calls the message.

    The chat id is part of it because a message id is only unique inside its
    chat on some platforms - Telegram numbers messages per chat and Slack's
    `ts` is per channel - so a bot-wide key would let one chat's message
    silently swallow another's.
    """
    return (
        f"channel:seen:{incoming.bot_id}:{incoming.platform}"
        f":{incoming.platform_chat_id}:{incoming.message_id}"
    )


async def claim_delivery(incoming: IncomingMessage) -> bool:
    """Claim this delivery. True means it is ours to process; False means an
    earlier delivery of the same message already was.

    Fails open, every time with a log line: a message with no platform
    message id, a module nothing configured, and a Redis that cannot be
    reached all answer True. Dropping a legitimate question is a worse
    failure than answering a redelivered one twice - the duplicate is the
    rarer event and costs money, the drop is silence in front of a user -
    so degrading means losing the guarantee, never the message.
    """
    if incoming.message_id is None:
        logger.warning(
            "Channel delivery has no message_id - processed without a dedupe claim: "
            "bot=%s platform=%s",
            incoming.bot_id,
            incoming.platform,
        )
        return True
    if _redis is None:
        logger.warning(
            "Channel dedupe not configured - delivery processed without a claim: "
            "bot=%s platform=%s message=%s",
            incoming.bot_id,
            incoming.platform,
            incoming.message_id,
        )
        return True
    try:
        return await _redis.set(_key(incoming), "1", ttl=SEEN_TTL_SECONDS, nx=True)
    except Exception:
        logger.warning("channel_dedupe_redis_unavailable", exc_info=True)
        return True


async def release_delivery(incoming: IncomingMessage) -> None:
    """Give the claim back, so a redelivery of a run that never finished is
    processed rather than mistaken for one that was.

    The claim is taken on receipt, not on completion. Without this, a run that
    dies mid-flight - a provider error, a task cancelled while the pod drains -
    swallows every redelivery of that message for the next fifteen minutes,
    which is the one way this module could lose a question rather than a
    duplicate. The polling paths make it concrete: aiogram re-fetches an
    unconfirmed `getUpdates` batch after a restart and Socket Mode redelivers an
    envelope it saw no acknowledgement for, and both would meet a claim that
    outlived the run it was taken for.

    Best effort, on the same reasoning as `claim_delivery`: a claim that cannot
    be given back costs one duplicate answer, where raising here would replace
    the failure the caller is already handling with this one.
    """
    if incoming.message_id is None or _redis is None:
        return
    try:
        await _redis.delete(_key(incoming))
    except Exception:
        logger.warning("channel_dedupe_release_failed", exc_info=True)
