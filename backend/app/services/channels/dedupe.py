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
routes - the router's chat lock is per-process on purpose, serialising the
turns one worker runs in one chat, and is no model to follow here. The router
takes a message's claim at the top of `route`, the one point all six inbound
paths cross, and gives it back if the run under it does not finish. A button
press that a platform may deliver twice is claimed by `process_channel_press`
and, a press being a quick decision, never given back, in a namespace of its own
(`pressed`). A next-step tap is then routed as a message under the same id; the
other taps are not.
"""

import hashlib
import logging

from app.clients.redis import RedisClient
from app.services.channels.base import IncomingMessage, IncomingPress

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


def _key(
    incoming: IncomingMessage | IncomingPress, delivery_id: str | None, prefix: str = "seen"
) -> str:
    """The claim's address: what the *platform* calls the message.

    The chat id is part of it because a message id is only unique inside its
    chat on some platforms - Telegram numbers messages per chat and Slack's
    `ts` is per channel - so a bot-wide key would let one chat's message
    silently swallow another's.

    `prefix` is the claim's namespace. A press is claimed as `pressed` and then
    may be routed as a message under the same id; sharing a namespace would make
    the router drop it as a duplicate of its own press.
    """
    return (
        f"channel:{prefix}:{incoming.bot_id}:{incoming.platform}"
        f":{incoming.platform_chat_id}:{delivery_id}"
    )


def _is_edited_mention(incoming: IncomingMessage) -> bool:
    return incoming.platform == "mattermost" and incoming.raw.get("event") == "post_edited"


async def remember_unaddressed(incoming: IncomingMessage) -> None:
    """Retain a short-lived edit candidate only for an observed, ignored post."""
    if (
        incoming.platform != "mattermost"
        or incoming.message_id is None
        or _redis is None
        or not incoming.dedupe_claimed
    ):
        return
    try:
        await _redis.set(_key(incoming, incoming.message_id), "ignored", ttl=SEEN_TTL_SECONDS)
    except Exception:
        logger.warning("channel_edit_candidate_unavailable", exc_info=True)


def delivery_ref(message_id: str | None) -> str | None:
    """A short, stable, non-reversible stand-in for a platform message id, for log lines.

    A message id is the platform's to define: WhatsApp's is base64 of ids that
    include the customer's phone number. So no line formats one; it logs this, which
    still lets an operator match a redelivery's lines to each other.
    """
    if message_id is None:
        return None
    return hashlib.sha256(message_id.encode()).hexdigest()[:12]


async def edited_delivery_is_eligible(incoming: IncomingMessage) -> bool:
    """Authorize an edit while its original ignored-post receipt still exists.

    Durable admission records this decision under its unique edit key. It does
    not spend a Redis claim before the PostgreSQL transaction can commit.
    """
    if not _is_edited_mention(incoming) or incoming.message_id is None or _redis is None:
        return False
    try:
        return await _redis.get(_key(incoming, incoming.message_id)) == "ignored"
    except Exception:
        logger.warning("channel_edited_eligibility_unavailable", exc_info=True)
        return False


async def claim_delivery(incoming: IncomingMessage) -> bool:
    """Claim this delivery. True means it is ours to process; False means an
    earlier delivery of the same message already was.

    New-post delivery fails open, every time with a log line: a message with no platform
    message id, a module nothing configured, and a Redis that cannot be
    reached all answer True. Dropping a legitimate question is a worse
    failure than answering a redelivered one twice - the duplicate is the
    rarer event and costs money, the drop is silence in front of a user -
    so degrading means losing the guarantee, never the message. Edited Mattermost
    mentions are admitted only with a shared receipt for an ignored original;
    they fail closed so an edit cannot replay a previously handled action.
    """
    incoming.dedupe_claimed = False
    if _is_edited_mention(incoming):
        # An edit may start work only for a post we observed and ignored. A
        # separate NX claim serializes edits without deleting the original's
        # receipt. Missing Redis or expired history never replays old actions.
        if incoming.message_id is None or _redis is None:
            return False
        try:
            if await _redis.get(_key(incoming, incoming.message_id)) != "ignored":
                return False
            return await _redis.set(
                f"{_key(incoming, incoming.message_id)}:edit", "1", ttl=SEEN_TTL_SECONDS, nx=True
            )
        except Exception:
            logger.warning("channel_edited_delivery_unavailable", exc_info=True)
            return False
    if incoming.message_id is None:
        logger.warning(
            "Channel delivery has no message_id - processed without a dedupe claim: "
            "bot=%s platform=%s",
            incoming.bot_id,
            incoming.platform,
        )
        return True
    admitted, claimed = await _claim(
        _key(incoming, incoming.message_id),
        bot_id=incoming.bot_id,
        platform=incoming.platform,
        ref=incoming.message_id,
    )
    incoming.dedupe_claimed = claimed
    return admitted


async def claim_press(press: IncomingPress) -> bool:
    """Claim this press's delivery, on the terms of `claim_delivery`.

    Only a platform that may deliver one press twice gives it a `delivery_id`
    (a tap's own message id); a press without one is always ours. The claim is per chat for the
    same reason a message's is.
    """
    if press.delivery_id is None:
        return True
    admitted, _ = await _claim(
        _key(press, press.delivery_id, "pressed"),
        bot_id=press.bot_id,
        platform=press.platform,
        ref=press.delivery_id,
    )
    return admitted


async def _claim(key: str, *, bot_id: str, platform: str, ref: str) -> tuple[bool, bool]:
    """Return admission and receipt separately; an unavailable store grants no receipt."""
    if _redis is None:
        logger.warning(
            "Channel dedupe not configured - delivery processed without a claim: "
            "bot=%s platform=%s message=%s",
            bot_id,
            platform,
            delivery_ref(ref),
        )
        return True, False
    try:
        claimed = await _redis.set(key, "1", ttl=SEEN_TTL_SECONDS, nx=True)
    except Exception:
        logger.warning("channel_dedupe_redis_unavailable", exc_info=True)
        return True, False
    else:
        return claimed, claimed


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
        key = (
            f"{_key(incoming, incoming.message_id)}:edit"
            if _is_edited_mention(incoming)
            else _key(incoming, incoming.message_id)
        )
        await _redis.delete(key)
    except Exception:
        logger.warning("channel_dedupe_release_failed", exc_info=True)


async def release_press(press: IncomingPress) -> None:
    """Permit a durable worker to retry a decision that did not finish."""
    if press.delivery_id is None or _redis is None:
        return
    try:
        await _redis.delete(_key(press, press.delivery_id, "pressed"))
    except Exception:
        logger.warning("channel_press_release_failed", exc_info=True)
