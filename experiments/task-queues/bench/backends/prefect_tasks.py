"""Prefect 3 background tasks: `task.delay()` and a long-lived task worker.

Run:
    python -m bench.backends.prefect_tasks

Prefect's own answer for light, frequent work: the task worker stays up and runs
each submitted task in-process, so there is no process per run - but every task
still goes through the Prefect server, and its parameters through result storage
both sides can read (`PREFECT_LOCAL_STORAGE_PATH`, a shared volume here). There is
no scheduler for background tasks, so it takes no part in the sweep measurement.
"""

import asyncio
from typing import Any

from prefect import task
from prefect.task_worker import serve

from bench import config, workload
from bench import heavy as _heavy  # noqa: F401 - the real application's import cost


@task(name="bench-run")
async def run_job(job: dict[str, Any]) -> None:
    await workload.run(job, submit)


async def submit(job: dict[str, Any]) -> None:
    run_job.delay(job)


if __name__ == "__main__":
    asyncio.run(serve(run_job, limit=config.CONCURRENCY))
