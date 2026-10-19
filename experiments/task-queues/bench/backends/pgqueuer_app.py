"""PgQueuer: a Postgres queue for asyncio, on asyncpg, with cron schedules.

Run:
    python -m bench.backends.pgqueuer_app

One process runs up to `BENCH_CONCURRENCY` jobs on one event loop. It claims with
`FOR UPDATE SKIP LOCKED`, wakes on `LISTEN/NOTIFY`, and heartbeats the jobs it
holds. A job whose heartbeat stops is picked again by any worker once it is older
than `heartbeat_timeout`.

A job that raises is retried by `DatabaseRetryEntrypointExecutor` up to
`max_attempts`. A job whose worker dies raises nothing: the stale re-pick does not
count an attempt (`adapters/persistence/qb.py` in 1.6.0), which is what the `oom`
scenario puts to the test.

It speaks asyncpg, the driver AgenticOS already uses.
"""

import asyncio
import json
from datetime import timedelta
from typing import Any

import asyncpg
from pgqueuer import DatabaseRetryEntrypointExecutor, PgQueuer, Queries
from pgqueuer.models import Job

from bench import config, workload
from bench import heavy as _heavy  # noqa: F401 - the real application's import cost

ENTRYPOINT = "bench.run"
MAX_ATTEMPTS = 3
HEARTBEAT_TIMEOUT = timedelta(seconds=30)

_pool: asyncpg.Pool | None = None


async def _shared_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(config.POSTGRES_DSN, min_size=1, max_size=config.CONCURRENCY + 4)
    return _pool


async def setup() -> None:
    queries = Queries.from_asyncpg_pool(await _shared_pool())
    if not await queries.has_table("pgqueuer"):
        await queries.install()


async def submit(job: dict[str, Any]) -> None:
    queries = Queries.from_asyncpg_pool(await _shared_pool())
    await queries.enqueue(ENTRYPOINT, json.dumps(job).encode())


async def serve() -> None:
    await setup()
    pgq = PgQueuer.from_asyncpg_pool(await _shared_pool())

    @pgq.entrypoint(
        ENTRYPOINT,
        executor_factory=lambda parameters: DatabaseRetryEntrypointExecutor(
            parameters=parameters, max_attempts=MAX_ATTEMPTS
        ),
    )
    async def run_job(job: Job) -> None:
        assert job.payload is not None
        await workload.run(json.loads(job.payload), submit)

    @pgq.schedule("bench.sweep", "* * * * *")
    async def sweep(_schedule: object) -> None:
        await workload.sweep()

    await pgq.run(max_concurrent_tasks=config.CONCURRENCY, heartbeat_timeout=HEARTBEAT_TIMEOUT)


if __name__ == "__main__":
    asyncio.run(serve())
