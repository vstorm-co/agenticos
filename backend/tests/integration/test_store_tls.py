"""Encrypted transport to Postgres works through the pool and the worker (#1418).

Skipped unless the configured Postgres accepts a TLS connection: a plaintext dev
container refuses `ssl=require`, so this proves nothing on `make test` and
everything on a managed Postgres or one told to require SSL. `pg_stat_ssl` reports
the transport of the connection actually made, not the setting that asked for it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.anyio


def _tls_url(database_url: str) -> str:
    """The test database's own URL - the one the session fixture created - asking
    for TLS. Built from the fixture rather than from `settings`, so the database
    exists whatever order the suite runs in."""
    return f"{database_url}?ssl=require"


async def _connection_is_encrypted(engine: AsyncEngine) -> bool:
    """Whether a connection from *engine* is TLS, as the server reports it."""
    async with engine.connect() as conn:
        answer = await conn.execute(
            text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
        )
        return bool(answer.scalar())


async def _connection_is_encrypted_or_skip(engine: AsyncEngine) -> bool:
    """The one outcome that proves nothing is a server without SSL at all, which
    asyncpg reports as `rejected SSL upgrade`. Anything else - a bad option, a
    certificate the client refuses, credentials, the network - is a failure of
    what this test exists to check, and propagates."""
    try:
        return await _connection_is_encrypted(engine)
    except Exception as exc:
        if "rejected SSL upgrade" in str(exc):
            pytest.skip("Postgres here does not accept ssl=require; nothing to prove")
        raise


async def test_the_pool_and_the_worker_engine_both_connect_with_tls(database_url: str):
    pool = create_async_engine(_tls_url(database_url), pool_size=1, max_overflow=0)
    try:
        assert await _connection_is_encrypted_or_skip(pool) is True

        # The Prefect worker opens its own engine on the same URL (see
        # `app/db/session.py`), so the setting has to carry through there too.
        worker = create_async_engine(_tls_url(database_url), poolclass=NullPool)
        try:
            assert await _connection_is_encrypted(worker) is True
        finally:
            await worker.dispose()
    finally:
        await pool.dispose()
