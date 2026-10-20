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
per worker this deployment had before - duplicates, never silence. A command
Redis refuses is not a Redis it cannot reach, and is not read as a lease held.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

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


_UNREACHABLE = (RedisConnectionError, RedisTimeoutError, OSError)
"""What says Redis could not be reached, as opposed to a command it refused."""


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
        self.untaken: set[str] = set()
        """Bots whose `take` did not reach Redis, written again on the next pass -
        or the holder it was meant to replace would win once Redis came back,
        and the edit that called it would be lost."""
        self.unwithdrawn: set[str] = set()
        """Bots whose `withdraw` did not reach Redis, deleted again on the next
        pass - or a paused bot would go on answering on another worker."""

    async def claim(self, bot_id: str) -> bool:
        """Take the bot's lease if nobody holds it. True when it is now this process's."""
        if self.redis is None:
            return True
        try:
            if await self.redis.set(_key(bot_id), self.holder, ttl=LEASE_SECONDS, nx=True):
                return True
            return await self.redis.get(_key(bot_id)) == self.holder
        except _UNREACHABLE:
            logger.warning("channel_stream_lease_unavailable", exc_info=True)
            return True

    async def holds(self, bot_id: str) -> bool:
        """Whether the bot's lease is still this process's - asked right before
        opening a stream a `claim` won, in case an edit or a pause came between."""
        if self.redis is None:
            return True
        try:
            return await self.redis.get(_key(bot_id)) == self.holder
        except _UNREACHABLE:
            logger.warning("channel_stream_lease_unavailable", exc_info=True)
            return True

    async def take(self, bot_id: str, platform: str) -> None:
        """Hold the bot's lease, whoever held it - see the module docstring."""
        self.held[bot_id] = platform
        self.unwithdrawn.discard(bot_id)
        if not await self._write(bot_id):
            self.untaken.add(bot_id)

    def hold(self, bot_id: str, platform: str) -> None:
        """Record a lease `claim` won, so it is renewed and given back at shutdown."""
        self.held[bot_id] = platform

    def drop(self, bot_id: str) -> None:
        """Forget a bot this process will not stream after all, leaving Redis alone."""
        self.held.pop(bot_id, None)
        self.untaken.discard(bot_id)

    async def withdraw(self, bot_id: str) -> None:
        """End the bot's lease, whoever held it: the bot is to have no stream."""
        self.drop(bot_id)
        if not await self._delete(bot_id):
            self.unwithdrawn.add(bot_id)

    async def renew(self) -> list[str]:
        """Renew every lease this process holds; close the streams of those it lost.

        A lease is lost when another worker took it for an edit, when the bot's
        stream was withdrawn, or when this process went long enough without
        renewing that it ran out. Each is closed through the adapter alone,
        never through `close_inbound_stream`, which would withdraw the lease the
        new holder has just taken. A `take` or a `withdraw` that did not reach
        Redis is written again first.

        Returns:
            The bots whose streams were closed.
        """
        for bot_id in list(self.unwithdrawn):
            if await self._delete(bot_id):
                self.unwithdrawn.discard(bot_id)
        lost: list[str] = []
        for bot_id, platform in list(self.held.items()):
            if bot_id in self.untaken:
                if await self._write(bot_id):
                    self.untaken.discard(bot_id)
                continue
            if await self._renewed(bot_id):
                continue
            del self.held[bot_id]
            lost.append(bot_id)
            logger.info(
                "%s: bot %s is served by another worker now; closing it on worker %s",
                platform.capitalize(),
                bot_id,
                self.holder,
            )
            await get_adapter(platform).stop_polling(bot_id)
        return lost

    async def _write(self, bot_id: str) -> bool:
        if self.redis is None:
            return True
        try:
            await self.redis.set(_key(bot_id), self.holder, ttl=LEASE_SECONDS)
        except _UNREACHABLE:
            logger.warning("channel_stream_lease_unavailable", exc_info=True)
            return False
        return True

    async def _delete(self, bot_id: str) -> bool:
        if self.redis is None:
            return True
        try:
            await self.redis.delete(_key(bot_id))
        except _UNREACHABLE:
            logger.warning("channel_stream_lease_withdraw_failed", exc_info=True)
            return False
        return True

    async def _renewed(self, bot_id: str) -> bool:
        """Whether this process still holds the lease, extended if it does.

        A read and then an expiry rather than one script: a deployment's Redis
        may refuse `EVAL`, and a renewal that could not be verified must not
        pass for one. The gap between the two is harmless - a worker that took
        the lease in it gets its own lease extended, and this one finds out at
        its next pass. Only an unreachable Redis is read as held: duplicates,
        never silence.
        """
        if self.redis is None:
            return True
        try:
            if await self.redis.get(_key(bot_id)) != self.holder:
                return False
            await self.redis.expire(_key(bot_id), LEASE_SECONDS)
        except _UNREACHABLE:
            logger.warning("channel_stream_lease_unavailable", exc_info=True)
        except Exception:
            logger.exception("Could not renew the stream lease of bot %s", bot_id)
            return False
        return True

    async def release_one(self, bot_id: str) -> None:
        """Give back a lease a pass claimed for a bot that turned out to want no stream."""
        self.drop(bot_id)
        if self.redis is None:
            return
        try:
            await self.redis.delete_if_equal(_key(bot_id), self.holder)
        except Exception:
            logger.warning("channel_stream_lease_release_failed", exc_info=True)

    async def release(self) -> None:
        """Give back every lease this process still holds, for a shutdown.

        Only a lease still its own: one another worker took in the meantime is
        that worker's, and deleting it would leave its bot unserved until the
        next pass noticed. One that cannot be given back runs out on its own.
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
