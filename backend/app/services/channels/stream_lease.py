"""Which process holds a polling bot's inbound stream (#2168).

A polling bot - Telegram long-polling, Slack Socket Mode, a Mattermost event
stream - is reached over a connection one process holds. Every API worker runs
the lifespan, and the lifespan opened a stream for every active polling bot, so
with `UVICORN_WORKERS=2` each bot had two. Telegram allows one `getUpdates` per
bot and terminated them in turn, about fourteen times a minute; two Mattermost
sockets each receive every event.

So each bot's stream is held under a lease in the Redis every worker shares:
one key per bot naming the process that holds it, with a short lifetime the
holder renews. A worker opens a stream only for a bot whose lease it holds, and
closes its copy the moment a renewal finds the lease is no longer its own. When
the holder stops, it gives its leases back and another worker claims them on its
next pass; when it dies, the lease runs out and the same happens a little later.

Two ways of getting a lease, on purpose. The startup pass and the periodic one
*claim* - only a lease nobody holds - because they are catching up with rows
another worker may already serve. A registration or an edit *takes* it, whoever
held it: that request is the newest word on the bot, so its worker opens the
stream with the new settings now, and the previous holder closes its copy at its
next renewal. A bot paused, deleted or switched to webhooks has its lease
*withdrawn* outright, so whichever worker held it stops at its next renewal and
no pass reopens it, because the row no longer asks for a stream.

Fails open, like the delivery dedupe beside it: with no Redis configured or none
reachable, every claim succeeds and every renewal holds, which is the one stream
per worker this deployment had before - duplicates, never silence.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from app.clients.redis import RedisClient
from app.services.channels import get_adapter

logger = logging.getLogger(__name__)

LEASE_SECONDS = 30
"""How long a lease outlives its last renewal - how long a worker that died
without giving its bots back keeps them from everyone else."""

RENEW_EVERY_SECONDS = 10.0
"""How often a holder renews its leases and every worker claims the free ones.

A third of the lease, so two renewals can be missed - a slow Redis, a busy
event loop - before a live holder loses a bot it is still serving.
"""


def _key(bot_id: str) -> str:
    return f"channel:stream:{bot_id}"


class StreamLeases:
    """One process's leases on the deployment's polling bots."""

    def __init__(self, redis: RedisClient | None, *, holder: str | None = None) -> None:
        self.redis = redis
        self.holder = holder or uuid4().hex
        """What this process writes into a lease - unique per process, so a
        worker can tell its own lease from a restarted neighbour's."""
        self.held: dict[str, str] = {}
        """The bots this process holds, by id, with the platform that serves each."""

    async def claim(self, bot_id: str) -> bool:
        """Take the bot's lease if nobody holds it. True when it is now this process's."""
        if self.redis is None:
            return True
        try:
            if await self.redis.set(_key(bot_id), self.holder, ttl=LEASE_SECONDS, nx=True):
                return True
            return await self.redis.get(_key(bot_id)) == self.holder
        except Exception:
            logger.warning("channel_stream_lease_unavailable", exc_info=True)
            return True

    async def take(self, bot_id: str, platform: str) -> None:
        """Hold the bot's lease, whoever held it - see the module docstring."""
        self.held[bot_id] = platform
        if self.redis is None:
            return
        try:
            await self.redis.set(_key(bot_id), self.holder, ttl=LEASE_SECONDS)
        except Exception:
            logger.warning("channel_stream_lease_unavailable", exc_info=True)

    def hold(self, bot_id: str, platform: str) -> None:
        """Record a lease `claim` won, so it is renewed and given back at shutdown."""
        self.held[bot_id] = platform

    async def withdraw(self, bot_id: str) -> None:
        """End the bot's lease, whoever held it: the bot is to have no stream."""
        self.held.pop(bot_id, None)
        if self.redis is None:
            return
        try:
            await self.redis.delete(_key(bot_id))
        except Exception:
            logger.warning("channel_stream_lease_withdraw_failed", exc_info=True)

    async def renew(self) -> list[str]:
        """Renew every lease this process holds; close the streams of those it lost.

        A lease is lost when another worker took it for an edit, when the bot's
        stream was withdrawn, or when this process went long enough without
        renewing that it ran out. Each is closed through the adapter alone,
        never through `close_inbound_stream`, which would withdraw the lease the
        new holder has just taken.

        Returns:
            The bots whose streams were closed.
        """
        lost: list[str] = []
        for bot_id, platform in list(self.held.items()):
            if await self._renewed(bot_id):
                continue
            del self.held[bot_id]
            lost.append(bot_id)
            logger.info("%s: bot %s is served by another worker now", platform.capitalize(), bot_id)
            await get_adapter(platform).stop_polling(bot_id)
        return lost

    async def _renewed(self, bot_id: str) -> bool:
        if self.redis is None:
            return True
        try:
            return await self.redis.expire_if_equal(_key(bot_id), self.holder, LEASE_SECONDS)
        except Exception:
            logger.warning("channel_stream_lease_unavailable", exc_info=True)
            return True

    async def release(self) -> None:
        """Give back every lease this process still holds, for a shutdown.

        Only a lease still its own: one another worker took in the meantime is
        that worker's, and deleting it would leave its bot unserved until the
        next pass noticed.
        """
        held, self.held = list(self.held), {}
        if self.redis is None:
            return
        for bot_id in held:
            try:
                await self.redis.delete_if_equal(_key(bot_id), self.holder)
            except Exception:
                logger.warning("channel_stream_lease_release_failed", exc_info=True)


_leases = StreamLeases(None)


def configure(redis: RedisClient | None) -> StreamLeases:
    """Start this process's leases against the shared Redis, or with `None`, none.

    Called by the lifespan next to where the client is created; a new lifespan
    starts a new holder with nothing held.
    """
    global _leases
    _leases = StreamLeases(redis)
    return _leases


def leases() -> StreamLeases:
    """This process's leases."""
    return _leases
