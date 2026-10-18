"""Celery + Beat on a Redis broker.

Run with the pool under test:
    celery -A bench.backends.celery_app worker --pool prefork --concurrency 4
    celery -A bench.backends.celery_app worker --pool threads --concurrency 20
    celery -A bench.backends.celery_app beat

The work is `async`, and Celery has no asyncio pool, so each worker thread (in the
prefork pool, each process) keeps one event loop for its life and runs every task
on it - the usual way to call async code from Celery without paying a new loop and
new connections per task. `acks_late` with `reject_on_worker_lost` returns a job to
the queue when its worker dies mid-task, which is at-least-once.
"""

import asyncio
import threading
from typing import Any

from celery import Celery

from bench import config, workload
from bench import heavy as _heavy  # noqa: F401 - the real application's import cost

app = Celery("bench", broker=config.REDIS_URL)
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 60},
    beat_schedule={"sweep": {"task": "bench.sweep", "schedule": float(config.SWEEP_SECONDS)}},
    task_default_queue="bench",
)

_local = threading.local()


def _run_async(coro: Any) -> Any:
    loop = getattr(_local, "loop", None)
    if loop is None:
        loop = asyncio.new_event_loop()
        _local.loop = loop
    return loop.run_until_complete(coro)


async def submit(job: dict[str, Any]) -> None:
    run_job.apply_async(args=[job])


@app.task(name="bench.run")
def run_job(job: dict[str, Any]) -> None:
    _run_async(workload.run(job, submit))


@app.task(name="bench.sweep")
def sweep() -> None:
    _run_async(workload.sweep())
