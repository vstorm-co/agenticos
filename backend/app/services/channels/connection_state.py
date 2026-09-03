"""Whether a bot's inbound connection is actually up, where somebody can see it.

A polling bot - Telegram long-polling, Slack Socket Mode, a Mattermost event
stream - is reached over a connection this process holds, and when that
connection does not open the bot is silent. Every cause was written to the
container log and nowhere else: `/channels` showed the row with its `Polling`
badge, an agent bound to it and no hint of a problem, so "the bot does not
answer" and "the bot is fine" were the same pixels (#1351).

The supervisors already know. What they lacked was somewhere to put it that a
listing could read, which is what this is: one entry per bot in the shared Redis,
written where a stream opens or gives up and read by the channels listing.

**Redis rather than a column.** This is the state of a process's socket, not a
fact about the organization's configuration - it is true of one deployment at one
moment, it changes without anybody editing anything, and a restart should forget
it rather than resurrect a stale "down" from last week. It expires for the same
reason: an entry nobody refreshed outlives the process that wrote it, and a bot
whose API worker was replaced is not down, it is unknown.

**Unconfigured is not unsafe, only blind.** With no Redis every bot reads as
`unknown`, which is what the listing showed before this existed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.clients.redis import RedisClient

logger = logging.getLogger(__name__)

TTL_SECONDS = 900
"""How long an entry outlives the supervisor that wrote it.

Long enough that a healthy bot nobody has touched still reads `up` - the streams
refresh on every open, and a quiet bot's entry is refreshed by nothing - and
short enough that a killed worker's last word is not still on screen an hour
later. Fifteen minutes, the same window the dedupe claim gets.
"""

ConnectionState = Literal["up", "down"]


@dataclass(frozen=True)
class ChannelConnection:
    """What the last supervisor to touch this bot's stream reported."""

    state: ConnectionState
    reason: str | None = None
    """Why it is down, in words an operator can act on.

    Never a vendor exception's text: this is rendered in the product, so it takes
    the same rule as `rag_documents.error_message` - what failed and what to do,
    with the client's own message in the log beside the call.
    """


_redis: RedisClient | None = None


def configure(redis: RedisClient | None) -> None:
    """Hand over the shared Redis client, or withdraw it with `None`.

    Called by the lifespan beside where the client is created, the same contract
    as `dedupe.configure` and `membership.configure`.
    """
    global _redis
    _redis = redis


def _key(bot_id: UUID | str) -> str:
    return f"channel:conn:{bot_id}"


async def record_up(bot_id: UUID | str) -> None:
    """The stream is open and receiving."""
    await _write(bot_id, ChannelConnection(state="up"))


async def record_down(bot_id: UUID | str, reason: str) -> None:
    """The stream is not running, and this is what an operator can do about it."""
    await _write(bot_id, ChannelConnection(state="down", reason=reason))


HEARTBEAT_SECONDS = TTL_SECONDS // 3
"""How often a live supervisor re-stamps its entry.

A third of the TTL, so two heartbeats can be missed before the entry expires -
one slow Redis round trip must not make a healthy bot read `unknown`.
"""


async def heartbeat(bot_id: UUID | str) -> None:
    """Keep this bot's `up` entry alive for as long as this task runs.

    Never returns; cancel it when the stream closes. It exists because
    `record_up` fires once, when the stream opens, and the entry expires after
    `TTL_SECONDS` - so every healthy Slack, Telegram or Mattermost connection
    read `unknown` after fifteen quiet minutes, and the channels listing lost
    its health signal during entirely normal operation.
    """
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await record_up(bot_id)


async def forget(bot_id: UUID | str) -> None:
    """Drop this bot's entry, for a bot being deleted or deliberately stopped.

    A paused bot has no connection *by design*, and the listing already says
    `Paused`; leaving a `down` beside it would report a decision as a fault.
    """
    if _redis is None:
        return
    try:
        await _redis.delete(_key(bot_id))
    except Exception:
        logger.warning("channel_connection_state_unavailable", exc_info=True)


async def _write(bot_id: UUID | str, connection: ChannelConnection) -> None:
    if _redis is None:
        return
    try:
        await _redis.set(
            _key(bot_id),
            json.dumps({"state": connection.state, "reason": connection.reason}),
            ttl=TTL_SECONDS,
        )
    except Exception:
        # Losing this costs the badge, never the bot. A supervisor must not fail
        # to open a stream because it could not describe itself.
        logger.warning("channel_connection_state_unavailable", exc_info=True)


async def read(bot_id: UUID | str) -> ChannelConnection | None:
    """What is known about this bot's connection, or `None` for "nothing".

    `None` covers both "no entry" and "no Redis", which the listing renders the
    same way: a bot whose state nobody recorded is unknown, not healthy and not
    broken. Claiming either would be the defect this module exists to fix, in the
    other direction.
    """
    if _redis is None:
        return None
    try:
        raw = await _redis.get(_key(bot_id))
    except Exception:
        logger.warning("channel_connection_state_unavailable", exc_info=True)
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        state = payload["state"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if state not in ("up", "down"):
        return None
    reason = payload.get("reason")
    return ChannelConnection(state=state, reason=str(reason) if reason else None)
