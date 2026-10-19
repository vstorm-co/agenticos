"""Procrastinate: a Postgres queue for Python, async, with periodic tasks.

Run:
    python -m bench.backends.procrastinate_app

One process runs up to `BENCH_CONCURRENCY` jobs on one event loop. A job's worker
heartbeats; the periodic `retry_stalled` task requeues jobs whose worker stopped
heartbeating, which is how a killed worker's work comes back - Procrastinate does
not do it on its own. This is the documentation's recipe: it counts an attempt on
every retry but caps none, so a job that kills its worker is retried for ever
unless the application adds its own limit.

It speaks psycopg 3, not asyncpg, so in AgenticOS it would be a second Postgres
driver beside the application's.
"""

import asyncio
import os
from typing import Any

from procrastinate import App, PsycopgConnector

from bench import config, workload
from bench import heavy as _heavy  # noqa: F401 - the real application's import cost

app = App(connector=PsycopgConnector(conninfo=config.POSTGRES_DSN))


async def setup() -> None:
    """Apply the schema once: the driver and the worker both call this."""
    import asyncpg

    conn = await asyncpg.connect(config.POSTGRES_DSN)
    try:
        exists = await conn.fetchval("SELECT to_regclass('procrastinate_jobs') IS NOT NULL")
    finally:
        await conn.close()
    if not exists:
        async with app.open_async():
            await app.schema_manager.apply_schema_async()


_open = False


async def submit(job: dict[str, Any]) -> None:
    global _open
    if not _open:
        await app.open_async()
        _open = True
    await run_job.defer_async(job=job)


@app.task(name="bench.run", queue="bench")
async def run_job(job: dict[str, Any]) -> None:
    await workload.run(job, submit)


@app.periodic(cron="* * * * *")
@app.task(name="bench.sweep", queue="bench")
async def sweep(timestamp: int) -> None:
    await workload.sweep()


@app.periodic(cron="* * * * *")
@app.task(name="bench.retry_stalled", queue="bench")
async def retry_stalled(timestamp: int) -> None:
    stalled = await app.job_manager.get_stalled_jobs(seconds_since_heartbeat=30)
    for job in stalled:
        await app.job_manager.retry_job(job)


async def serve() -> None:
    await setup()
    async with app.open_async():
        await app.run_worker_async(
            queues=["bench"], concurrency=config.CONCURRENCY, wait=True, install_signal_handlers=True
        )


if __name__ == "__main__":
    os.environ.setdefault("PROCRASTINATE_VERBOSE", "0")
    asyncio.run(serve())
