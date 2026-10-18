"""Taskiq on Redis Streams, with its scheduler.

Run:
    taskiq worker bench.backends.taskiq_app:broker --workers 2 --max-async-tasks 20
    taskiq scheduler bench.backends.taskiq_app:scheduler

Async from end to end: one event loop per worker process runs up to
`--max-async-tasks` tasks at once. The stream broker acknowledges a message only
after its task returns, so a killed worker's message is claimed again by another
consumer once it has been idle for `idle_timeout`.
"""

from typing import Any

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisStreamBroker

from bench import config, workload
from bench import heavy as _heavy  # noqa: F401 - the real application's import cost

broker = RedisStreamBroker(url=config.REDIS_URL, idle_timeout=60_000)
scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])


async def submit(job: dict[str, Any]) -> None:
    await run_job.kiq(job)


@broker.task(task_name="bench.run")
async def run_job(job: dict[str, Any]) -> None:
    await workload.run(job, submit)


# Cron has minute granularity, which is the production interval anyway.
@broker.task(task_name="bench.sweep", schedule=[{"cron": "* * * * *"}])
async def sweep() -> None:
    await workload.sweep()
