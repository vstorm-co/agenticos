"""The background worker process (#2219).

Run with:

    python -m app.worker                       # every pool, from WORKER_POOLS
    python -m app.worker --pools agent,system  # some of them

One long-lived process imports the application once and serves the pools it
is given: agent runs and the system sweeps on its own loop, ingestion in child
processes with a memory limit each. It writes the declared schedules on start,
stops claiming on SIGTERM, lets running jobs finish for a while and gives the
rest back with their attempt, and exits.
"""

import argparse
import asyncio
import logging
import os
import secrets
import signal
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import settings
from app.core.logfire_setup import setup_worker_observability
from app.core.logging import setup_logging
from app.db.session import claim_pooled_engines, close_db, get_db_context
from app.services.background_jobs import tell_owners_paused
from app.worker import jobs, schedules
from app.worker.executors import ChildPool, Executor, InProcessExecutor
from app.worker.handlers import production, settle_ended
from app.worker.jobs import Pool
from app.worker.listener import asyncpg_dsn, listener
from app.worker.runtime import Worker, WorkerSettings

logger = logging.getLogger(__name__)


def pools_from(value: str) -> list[Pool]:
    """`agent,ingest` as pools, refusing a name that is not one."""
    names = [name.strip() for name in value.split(",") if name.strip()]
    if not names:
        raise ValueError("a worker needs at least one pool")
    return [Pool(name) for name in names]


def executors_for(pools: list[Pool]) -> dict[Pool, Executor]:
    # A worker serving only ingestion runs no handler itself; its children load
    # their own, so the parent does not import the agent runtime for nothing.
    handlers = production() if any(pool is not Pool.INGEST for pool in pools) else {}
    executors: dict[Pool, Executor] = {}
    for pool in pools:
        if pool is Pool.INGEST:
            executors[pool] = ChildPool(
                size=settings.WORKER_INGEST_CHILDREN,
                handlers="app.worker.handlers:ingest",
                memory_limit_bytes=settings.WORKER_INGEST_MEMORY_MB * 2**20,
                max_jobs=settings.WORKER_INGEST_MAX_JOBS,
            )
        elif pool is Pool.AGENT:
            executors[pool] = InProcessExecutor(
                handlers, concurrency=settings.WORKER_AGENT_CONCURRENCY
            )
        else:
            executors[pool] = InProcessExecutor(
                handlers, concurrency=settings.WORKER_SYSTEM_CONCURRENCY
            )
    return executors


async def serve(pools: list[Pool]) -> None:
    from app.services import browse_plans, change_feed, live_browse

    claim_pooled_engines()
    # A fired routine publishes to an open Activity page, can be watched browsing
    # and replays its last plan - each needs a Redis this process opens once.
    await change_feed.connect_in_worker()
    await live_browse.connect_in_worker()
    await browse_plans.connect_in_worker()
    async with get_db_context() as db:
        await schedules.declare(db, schedules.SCHEDULES, now=datetime.now(UTC))

    hostname = socket.gethostname()
    worker = Worker(
        settings=WorkerSettings(
            worker_id=f"{hostname}:{os.getpid()}:{secrets.token_hex(3)}",
            hostname=hostname,
            lease=timedelta(seconds=settings.WORKER_LEASE_SECONDS),
            breaker_deaths=settings.WORKER_BREAKER_DEATHS,
            health_file=Path(settings.WORKER_HEALTH_FILE),
        ),
        executors=executors_for(pools),
        tasks=jobs.TASKS,
        sessions=get_db_context,
        on_pause=tell_owners_paused,
        on_ended=settle_ended,
        schedule=lambda db: schedules.fire_due(db, schedules.SCHEDULES, now=datetime.now(UTC)),
        listen=listener(asyncpg_dsn(settings.DATABASE_URL)),
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    logger.info("background_worker_started", extra={"pools": [pool.value for pool in pools]})
    try:
        await worker.run(stop)
    finally:
        await close_db()
    logger.info("background_worker_stopped")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--pools", default=settings.WORKER_POOLS)
    args = parser.parse_args()
    pools = pools_from(args.pools)
    # The worker runs ingestion, syncs and reports - the code most likely to log a
    # connector 401 or an embedding-key failure - so it redacts like the API does (#440).
    setup_logging()
    setup_worker_observability()
    asyncio.run(serve(pools))


if __name__ == "__main__":  # pragma: no cover - the process entry point
    main()
