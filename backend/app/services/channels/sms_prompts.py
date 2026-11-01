"""Answering an approval or a question by texting its number (#2082).

An SMS has no buttons, so a prompt is sent as numbered lines and the person replies with the
number. Several prompts can be waiting on one number at once - a run that parks two
approvals sends two texts - so the numbers never repeat: the second prompt carries on from
where the first stopped (3 and 4, not 1 and 2), and each reply names exactly one choice of
one prompt.

What a number means is remembered per bot and chat for a day, in the deployment's shared
Redis because the reply may reach a different worker than the one that sent the prompt.
It is only the way to name a choice, not the approval's state: a prompt is dropped when the
router settles it, when its owner changes, or when a day passes. A reply that is a number
with nothing pending, or one that names no choice, is an ordinary message, so a person is
never silenced by a prompt they ignored.
"""

import json
import logging

from app.clients.redis import RedisClient
from app.services.channels.base import read_press

logger = logging.getLogger(__name__)

TTL_SECONDS = 24 * 60 * 60
"""How long a numbered prompt stays answerable; an approval left longer is for the console."""

MAX_DIGITS = 3
"""A reply longer than this is a sentence, not a choice."""

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`."""
    global _redis
    _redis = redis


def _key(bot_id: str, chat_id: str) -> str:
    return f"channel:sms:prompt:{bot_id}:{chat_id}"


async def _pending(bot_id: str, chat_id: str) -> dict[str, str]:
    if _redis is None:
        return {}
    stored = await _redis.get(_key(bot_id, chat_id))
    return json.loads(stored) if stored else {}


async def first_number(bot_id: str, chat_id: str) -> int:
    """The number the next prompt's first choice should carry: one past whatever is waiting."""
    return max((int(code) for code in await _pending(bot_id, chat_id)), default=0) + 1


async def remember(bot_id: str, chat_id: str, values: list[str], *, start: int) -> None:
    """Keep what the numbers of a prompt that was delivered mean, beside any still waiting.

    Called after the text went out: a prompt the person never received must not stay
    answerable, because a later digit from them could then decide it.
    """
    if _redis is None:
        return
    pending = await _pending(bot_id, chat_id)
    pending.update({str(start + offset): value for offset, value in enumerate(values)})
    await _redis.set(_key(bot_id, chat_id), json.dumps(pending), ttl=TTL_SECONDS)


async def forget(bot_id: str, chat_id: str) -> None:
    """Drop everything pending for this number - its owner changed."""
    if _redis is not None:
        await _redis.delete(_key(bot_id, chat_id))


async def settle(bot_id: str, chat_id: str, value: str) -> None:
    """Drop the prompt a decided choice belonged to, and leave any other one waiting."""
    pressed = read_press(value)
    if _redis is None or pressed is None:
        return
    pending = await _pending(bot_id, chat_id)
    kept = {
        code: choice
        for code, choice in pending.items()
        if (read_press(choice) or ("", None))[0] != pressed[0]
    }
    if kept:
        await _redis.set(_key(bot_id, chat_id), json.dumps(kept), ttl=TTL_SECONDS)
    else:
        await _redis.delete(_key(bot_id, chat_id))


async def answer(bot_id: str, chat_id: str, text: str) -> str | None:
    """The value of the choice a numeric reply names, or `None` when it names none.

    Not consumed by answering: a multi-select takes several replies and a Done, and the
    router decides when a prompt is settled - a second decision on an approval is refused
    there, so a repeated delivery of the same number does no harm.
    """
    digits = text.strip()
    if len(digits) > MAX_DIGITS or not digits.isdigit() or digits.startswith("0"):
        return None
    return (await _pending(bot_id, chat_id)).get(digits)
