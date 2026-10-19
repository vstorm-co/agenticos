"""Wakes a worker's pools the moment a job for them commits (#2219).

`LISTEN` needs a connection of its own, held open, so this is a plain asyncpg
connection rather than one borrowed from the pool. It is a latency
optimisation and nothing more: when it is down the pools still poll every
`poll_every` seconds, so a lost connection costs seconds of delay, never a job.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable

import asyncpg

from app.repositories.background_job import NOTIFY_CHANNEL
from app.worker.runtime import Listen

logger = logging.getLogger(__name__)


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    """The application's `postgresql+asyncpg://` URL in the form asyncpg itself takes."""
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def listener(dsn: str, *, reconnect_cap: float = 30.0, check_every: float = 30.0) -> Listen:
    """A loop that listens on `dsn` and calls back with each notified pool, until cancelled."""

    async def listen(notify: Callable[[str], None]) -> None:
        failures = 0
        while True:
            try:
                connection = await asyncpg.connect(dsn)
            except OSError, asyncpg.PostgresError, TimeoutError:
                failures += 1
                logger.warning("background_listener_connect_failed", exc_info=True)
                await asyncio.sleep(min(2.0**failures, reconnect_cap))
                continue
            failures = 0
            try:
                await _serve(connection, notify, check_every)
                logger.warning("background_listener_disconnected")
            finally:
                if not connection.is_closed():
                    await connection.close()

    return listen


async def _serve(
    connection: asyncpg.Connection, notify: Callable[[str], None], check_every: float
) -> None:
    closed = asyncio.Event()
    connection.add_termination_listener(lambda _connection: closed.set())
    await connection.add_listener(NOTIFY_CHANNEL, lambda _conn, _pid, _channel, pool: notify(pool))
    await _until_lost(connection, closed, check_every)


async def _until_lost(
    connection: asyncpg.Connection, closed: asyncio.Event, check_every: float
) -> None:
    """Return once the connection is gone - closed, or silently dead under a dropped network.

    A termination callback alone misses a peer that vanished without a FIN, so
    the connection is also asked a trivial question every `check_every` seconds.
    """
    while not closed.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(closed.wait(), timeout=check_every)
            return
        try:
            await asyncio.wait_for(connection.execute("SELECT 1"), timeout=10)
        except OSError, asyncpg.PostgresError, asyncpg.InterfaceError, TimeoutError:
            return
