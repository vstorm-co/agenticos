"""Answering an approval or a question by texting its number (#2082).

An SMS has no buttons, so a prompt is sent as numbered lines and the person replies with
the number. What a bare digit means depends on what was last asked of that number, so the
choices are remembered per bot and chat for a day: the next reply that is one digit and
fits is the answer, and is used once. Anything else - a digit with nothing pending, or one
past the last choice - is an ordinary message, so a person is never silenced by a prompt
they ignored.

In the deployment's shared Redis because the reply may reach a different worker than the
one that sent the prompt; nothing here is the approval's state, only the way to name it.
"""

import json
import logging

from app.clients.redis import RedisClient

logger = logging.getLogger(__name__)

TTL_SECONDS = 24 * 60 * 60
"""How long a numbered prompt stays answerable; an approval left longer is for the console."""

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`."""
    global _redis
    _redis = redis


def _key(bot_id: str, chat_id: str) -> str:
    return f"channel:sms:prompt:{bot_id}:{chat_id}"


async def remember(bot_id: str, chat_id: str, values: list[str]) -> None:
    """Keep the values of the choices just offered, replacing any earlier prompt."""
    if _redis is None:
        return
    await _redis.set(_key(bot_id, chat_id), json.dumps(values), ttl=TTL_SECONDS)


async def answer(bot_id: str, chat_id: str, text: str) -> str | None:
    """The value of the choice a one-digit reply names, or `None` when it names none.

    Not consumed by answering: a multi-select question takes several replies and a Done, and
    the router decides when a prompt is settled - a second decision on an approval is refused
    there, so a repeated delivery of the same digit does no harm. The next prompt sent to the
    number replaces this one, and a day ends it.
    """
    digits = text.strip()
    if _redis is None or len(digits) != 1 or not digits.isdigit() or digits == "0":
        return None
    stored = await _redis.get(_key(bot_id, chat_id))
    if stored is None:
        return None
    values: list[str] = json.loads(stored)
    index = int(digits) - 1
    return values[index] if index < len(values) else None
