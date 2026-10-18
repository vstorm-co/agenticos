"""SAQ (Simple Async Queue) on Redis, with its cron jobs.

Run:
    saq bench.backends.saq_app.settings --workers 2

Async, one loop per worker process running up to `concurrency` jobs. A job whose
worker died is retried once its `timeout` and the sweep that notices it pass.
"""

from typing import Any

from saq import CronJob, Queue

from bench import config, workload
from bench import heavy as _heavy  # noqa: F401 - the real application's import cost

queue = Queue.from_url(config.REDIS_URL, name="bench")


async def submit(job: dict[str, Any]) -> None:
    await queue.enqueue("bench_run", job=job, timeout=600, retries=2)


async def bench_run(ctx: dict[str, Any], *, job: dict[str, Any]) -> None:
    await workload.run(job, submit)


async def sweep(ctx: dict[str, Any]) -> None:
    await workload.sweep()


settings = {
    "queue": queue,
    "functions": [bench_run],
    "concurrency": config.CONCURRENCY,
    "cron_jobs": [CronJob(sweep, cron="* * * * *")],
}
