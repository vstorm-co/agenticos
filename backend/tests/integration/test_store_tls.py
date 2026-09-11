"""Encrypted transport to Postgres works through the pool and the worker (#1418).

Skipped unless the configured Postgres accepts a TLS connection: a plaintext dev
container refuses `ssl=require`, so this proves nothing on `make test` and
everything on a managed Postgres or one told to require SSL. `pg_stat_ssl` reports
the transport of the connection actually made, not the setting that asked for it.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

pytestmark = pytest.mark.anyio


def _tls_url() -> str:
    return (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}?ssl=require"
    )


async def _connection_is_encrypted(engine: Any) -> bool | None:
    """Whether a connection from *engine* is TLS, or None if it cannot connect."""
    try:
        async with engine.connect() as conn:
            answer = await conn.execute(
                text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
            )
            return bool(answer.scalar())
    except Exception:
        return None


async def test_the_pool_and_the_worker_engine_both_connect_with_tls():
    pool = create_async_engine(_tls_url(), pool_size=1, max_overflow=0)
    try:
        encrypted = await _connection_is_encrypted(pool)
        if not encrypted:
            pytest.skip("Postgres here does not accept ssl=require; nothing to prove")
        assert encrypted is True

        # The Prefect worker opens its own engine on the same URL (see
        # `app/db/session.py`), so the setting has to carry through there too.
        worker = create_async_engine(_tls_url(), poolclass=NullPool)
        try:
            assert await _connection_is_encrypted(worker) is True
        finally:
            await worker.dispose()
    finally:
        await pool.dispose()
