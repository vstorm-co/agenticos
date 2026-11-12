"""Answering an approval or a question by replying with its number (#2082).

An SMS has no buttons, so a prompt is sent as numbered lines and the person replies with the
number. Several prompts can be waiting on one number at once - a run that parks two
approvals sends two texts - so the numbers never repeat: the second prompt carries on from
where the first stopped (3 and 4, not 1 and 2), and each reply names exactly one choice of
one prompt.

What a number means is remembered per bot and chat, in the deployment's shared Redis
because the reply may reach a different worker than the one that sent the prompt. It is
only the way to name a choice, not the approval's state: a prompt is dropped when the
router settles it or its owner changes, and each number stops answering a day after it
was handed out. A reply that is a number with nothing pending, or one that names no
choice, is an ordinary message, so a person is never silenced by a prompt they ignored.

Three digits run out, so numbering wraps around after 999. A number is handed out again
only once nothing waits on it and a week has passed since it last was, so a late reply to
an old text cannot decide a newer request unless it is over a week late.

SMS and e-mail share this: neither has buttons, and `platform` keeps their numbers apart.
"""

import json
import logging

from app.clients.redis import RedisClient
from app.services.channels.base import read_press
from app.services.channels.exceptions import ChannelNotConfigured

logger = logging.getLogger(__name__)

TTL_SECONDS = 24 * 60 * 60
"""How long a numbered prompt stays answerable; an approval left longer is for the console."""

QUARANTINE_SECONDS = 7 * 24 * 60 * 60
"""How long a number is not handed out again after it was."""

NUMBERING_TTL_SECONDS = 90 * 24 * 60 * 60
"""How long a quiet chat keeps its place in the numbering before it starts again at 1."""

MAX_DIGITS = 3
"""A reply longer than this is a sentence, not a choice."""

_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`."""
    global _redis
    _redis = redis


def _key(bot_id: str, chat_id: str, platform: str) -> str:
    return f"channel:{platform}:prompt:{bot_id}:{chat_id}"


async def reserve(bot_id: str, chat_id: str, count: int, *, platform: str = "sms") -> int:
    """Reserve before sending so concurrent workers never advertise the same choices.

    A failed send leaves a gap, not an answerable prompt. A number is not handed out
    again while it waits or within `QUARANTINE_SECONDS`: a delayed reply must never
    decide a later approval.
    """
    if _redis is None:
        raise ChannelNotConfigured("Numbered replies require the shared prompt store.")
    key = _key(bot_id, chat_id, platform)
    start = await _redis.reserve_numbers(
        key + ":counter",
        issued=key + ":issued",
        pending=key,
        count=count,
        highest=10**MAX_DIGITS - 1,
        quarantine=QUARANTINE_SECONDS,
        answerable=TTL_SECONDS,
        ttl=NUMBERING_TTL_SECONDS,
    )
    if start == 0:
        raise ChannelNotConfigured("Too many pending choices; decide this request in the console.")
    return start


async def remember(
    bot_id: str, chat_id: str, values: list[str], *, start: int, platform: str = "sms"
) -> None:
    """Keep what the numbers of a prompt that was delivered mean, beside any still waiting.

    Called after the text went out: a prompt the person never received must not stay
    answerable, because a later digit from them could then decide it.
    """
    if _redis is None:
        return
    await _redis.update_mapping(
        _key(bot_id, chat_id, platform),
        updates={str(start + offset): value for offset, value in enumerate(values)},
        ttl=TTL_SECONDS,
    )


async def forget(bot_id: str, chat_id: str, *, platform: str = "sms") -> None:
    """Drop everything pending for this number - its owner changed."""
    if _redis is not None:
        await _redis.delete(_key(bot_id, chat_id, platform))


async def settle(bot_id: str, chat_id: str, value: str, *, platform: str = "sms") -> None:
    """Drop the prompt a decided choice belonged to, and leave any other one waiting."""
    pressed = read_press(value)
    if _redis is None or pressed is None:
        return
    stored = await _redis.get(_key(bot_id, chat_id, platform))
    pending: dict[str, str] = json.loads(stored) if stored else {}
    remove = [
        code
        for code, choice in pending.items()
        if (read_press(choice) or ("", None))[0] == pressed[0]
    ]
    await _redis.update_mapping(
        _key(bot_id, chat_id, platform), updates={}, remove=remove, ttl=TTL_SECONDS
    )


async def answer(bot_id: str, chat_id: str, text: str, *, platform: str = "sms") -> str | None:
    """The value of the choice a numeric reply names, or `None` when it names none.

    Not consumed by answering: a multi-select takes several replies and a Done, and the
    router decides when a prompt is settled - a second decision on an approval is refused
    there, so a repeated delivery of the same number does no harm.
    """
    digits = text.strip()
    if _redis is None or len(digits) > MAX_DIGITS or not digits.isdigit() or digits.startswith("0"):
        return None
    key = _key(bot_id, chat_id, platform)
    return await _redis.numbered_answer(key, issued=key + ":issued", number=digits, ttl=TTL_SECONDS)
