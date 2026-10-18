"""Where every task says when it started and finished - one clock for every backend.

A task writes `started` before its work and `finished` after it, each with the wall
time of this host and the process that ran it. The submitter wrote `enqueued` when
it handed the job to the backend. Queue wait, run time, the gap between workflow
steps, lost work (started, never finished) and duplicate work (finished twice) all
come from these rows.
"""

import asyncio
import os
import socket
import threading
import time
from typing import Any

import asyncpg

from bench import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS bench_jobs (
    job_id text PRIMARY KEY,
    run_label text NOT NULL,
    kind text NOT NULL,
    tenant text NOT NULL,
    chain_id text,
    step int,
    enqueued_at double precision NOT NULL
);
CREATE TABLE IF NOT EXISTS bench_events (
    id bigserial PRIMARY KEY,
    job_id text NOT NULL,
    event text NOT NULL,
    at double precision NOT NULL,
    worker text NOT NULL
);
CREATE INDEX IF NOT EXISTS bench_events_job ON bench_events (job_id);
"""

_local = threading.local()


async def _pool() -> asyncpg.Pool:
    """One small pool per event loop: Celery's thread pool runs a loop per thread."""
    loop = asyncio.get_running_loop()
    pools: dict[int, asyncpg.Pool] = getattr(_local, "pools", {})
    _local.pools = pools
    pool = pools.get(id(loop))
    if pool is None:
        pool = await asyncpg.create_pool(config.POSTGRES_DSN, min_size=1, max_size=4)
        pools[id(loop)] = pool
    return pool


def worker_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


async def mark(job_id: str, event: str) -> None:
    pool = await _pool()
    await pool.execute(
        "INSERT INTO bench_events (job_id, event, at, worker) VALUES ($1, $2, $3, $4)",
        job_id,
        event,
        time.time(),
        worker_name(),
    )


async def ensure_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(SCHEMA)


async def record_enqueued(conn: asyncpg.Connection, rows: list[dict[str, Any]]) -> None:
    await conn.executemany(
        "INSERT INTO bench_jobs (job_id, run_label, kind, tenant, chain_id, step, enqueued_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (job_id) DO NOTHING",
        [
            (
                r["job_id"],
                r["run_label"],
                r["kind"],
                r["tenant"],
                r.get("chain_id"),
                r.get("step"),
                r["enqueued_at"],
            )
            for r in rows
        ],
    )
