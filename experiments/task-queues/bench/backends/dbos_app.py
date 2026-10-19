"""DBOS Transact: durable workflows and queues in a library, on Postgres alone.

Run:
    python -m bench.backends.dbos_app

One process dequeues up to `BENCH_CONCURRENCY` workflows from the `bench` queue
and runs the async ones on its own event loop. The dequeue that hands a workflow
out also counts it (`recovery_attempts + 1`), so a workflow that kills its worker
still spends a dispatch. One dispatched more than `max_recovery_attempts + 1` times
is moved to `MAX_RECOVERY_ATTEMPTS_EXCEEDED` instead of being run again.

Without DBOS Conductor nothing watches for a dead process. A restarted process
recovers the PENDING workflows recorded under its own executor ID, so each worker
takes its container's hostname, which survives a restart, as that ID. A worker
that comes back as a new container (a deploy, `--force-recreate`) has a new ID,
and nothing recovers the old one's workflows: see `probes/dbos-recreate.sh`.

It speaks psycopg 3 through SQLAlchemy, not asyncpg, so in AgenticOS it would be a
second Postgres driver beside the application's.
"""

import asyncio
import os
from datetime import datetime
from typing import Any

from dbos import DBOS, DBOSClient, DBOSConfig, EnqueueOptions

from bench import config, workload
from bench import heavy as _heavy  # noqa: F401 - the real application's import cost

QUEUE = "bench"
WORKFLOW = "bench.run"
# Workers dequeue only their own version, so the client stamps it too.
APP_VERSION = "bench"
# Three dispatches in all: the first and two recoveries.
MAX_RECOVERY_ATTEMPTS = (int(os.environ.get("BENCH_MAX_ATTEMPTS", "0")) or 3) - 1
# DBOS polls its queues; one second is its default, `dbos-poll100` tries a tenth.
POLL_SECONDS = float(os.environ.get("BENCH_DBOS_POLL", "1.0"))

_client: DBOSClient | None = None


def _system_url() -> str:
    return config.POSTGRES_DSN.replace("postgresql://", "postgresql+psycopg://", 1)


def _shared_client() -> DBOSClient:
    global _client
    if _client is None:
        _client = DBOSClient(system_database_url=_system_url())
    return _client


async def setup() -> None:
    """Create DBOS's system schema; the driver and every worker call this."""
    from dbos import run_dbos_database_migrations

    await asyncio.to_thread(run_dbos_database_migrations, _system_url())


async def submit(job: dict[str, Any]) -> None:
    options: EnqueueOptions = {"queue_name": QUEUE, "workflow_name": WORKFLOW, "app_version": APP_VERSION}
    await _shared_client().enqueue_async(options, job)


@DBOS.workflow(name=WORKFLOW, max_recovery_attempts=MAX_RECOVERY_ATTEMPTS)
async def run_job(job: dict[str, Any]) -> None:
    await workload.run(job, submit)


@DBOS.workflow(name="bench.sweep", max_recovery_attempts=0)
async def sweep(_scheduled_at: datetime, _context: Any) -> None:
    await workload.sweep()


async def serve() -> None:
    dbos_config: DBOSConfig = {
        "name": "bench",
        "system_database_url": _system_url(),
        "executor_id": os.environ.get("HOSTNAME", "local"),
        "application_version": APP_VERSION,
    }
    DBOS(config=dbos_config)
    DBOS.launch()
    await DBOS.register_queue_async(QUEUE, worker_concurrency=config.CONCURRENCY, polling_interval_sec=POLL_SECONDS)
    try:
        await DBOS.create_schedule_async(schedule_name="bench.sweep", workflow_fn=sweep, schedule="0 * * * * *")
    except Exception as exc:
        # Every worker tries to create it; the first wins and the rest find it there.
        if "already exists" not in str(exc):
            raise
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(serve())
