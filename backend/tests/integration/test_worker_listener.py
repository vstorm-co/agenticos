"""The listener loses its connection and finds it again (#2219).

It is a latency optimisation - the pools poll without it - so what matters is
that a refused connection, a backend the server terminated and a connection
that went silent each end in a reconnect rather than a listener that is quietly
gone for the rest of the worker's life.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories import background_job as job_repo
from app.worker.listener import _until_lost, asyncpg_dsn, listener

pytestmark = pytest.mark.anyio


async def _until_logged(caplog: pytest.LogCaptureFixture, message: str, times: int = 1) -> None:
    async with asyncio.timeout(10):
        while True:
            if sum(record.message == message for record in caplog.records) >= times:
                return
            await asyncio.sleep(0.02)


async def test_a_refused_connection_is_retried_with_a_pause(
    caplog: pytest.LogCaptureFixture,
) -> None:
    listen = listener("postgresql://nobody@127.0.0.1:1/none", reconnect_cap=0.01)
    with caplog.at_level(logging.WARNING, logger="app.worker.listener"):
        serving = asyncio.create_task(listen(lambda _pool: None))
        try:
            await _until_logged(caplog, "background_listener_connect_failed", times=2)
        finally:
            serving.cancel()
            await asyncio.gather(serving, return_exceptions=True)


async def test_a_backend_the_server_terminated_is_listened_on_again(
    engine, schema_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    woken: asyncio.Queue[str] = asyncio.Queue()
    listen = listener(asyncpg_dsn(schema_url), reconnect_cap=0.01)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    with caplog.at_level(logging.WARNING, logger="app.worker.listener"):
        serving = asyncio.create_task(listen(woken.put_nowait))
        try:
            await _until_listening(sessions, 1)
            async with sessions() as db, db.begin():
                await db.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE query LIKE 'LISTEN%' AND pid <> pg_backend_pid()"
                    )
                )
            await _until_logged(caplog, "background_listener_disconnected")
            await _until_listening(sessions, 1)
            async with sessions() as db, db.begin():
                await job_repo.add(
                    db, kind="probe", pool="ingest", payload={}, max_attempts=1, priority=1
                )
            assert await asyncio.wait_for(woken.get(), timeout=5) == "ingest"
        finally:
            serving.cancel()
            await asyncio.gather(serving, return_exceptions=True)


async def _until_listening(sessions: async_sessionmaker[AsyncSession], count: int) -> None:
    async with asyncio.timeout(10):
        while True:
            async with sessions() as db:
                listening = await db.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE query LIKE 'LISTEN%' AND pid <> pg_backend_pid()"
                    )
                )
            if listening == count:
                return
            await asyncio.sleep(0.05)


async def test_a_connection_that_stops_answering_counts_as_lost() -> None:
    """A peer gone without a FIN never fires the termination callback; the check catches it."""
    connection = MagicMock(execute=AsyncMock(side_effect=asyncpg.InterfaceError("gone")))

    await asyncio.wait_for(_until_lost(connection, asyncio.Event(), check_every=0.01), timeout=5)

    connection.execute.assert_awaited_once_with("SELECT 1")


async def test_a_connection_that_answers_is_kept_until_it_closes() -> None:
    closed = asyncio.Event()
    answers = 0

    async def execute(_query: str) -> str:
        nonlocal answers
        answers += 1
        if answers == 2:
            closed.set()
        return "SELECT 1"

    await asyncio.wait_for(
        _until_lost(MagicMock(execute=execute), closed, check_every=0.01), timeout=5
    )
    assert answers == 2
