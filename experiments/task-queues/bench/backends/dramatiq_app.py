"""Dramatiq on Redis, async actors through its AsyncIO middleware.

Run:
    dramatiq bench.backends.dramatiq_app --processes 2 --threads 20

Dramatiq has no scheduler of its own (periodiq or APScheduler are the usual
add-ons), so it takes no part in the scheduled-sweep measurement. Messages are
acknowledged after the actor returns; a killed worker's messages come back once
Redis notices the dead consumer (its heartbeat timeout).
"""

from typing import Any

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware.asyncio import AsyncIO

from bench import config, workload
from bench import heavy as _heavy  # noqa: F401 - the real application's import cost

broker = RedisBroker(url=config.REDIS_URL)
broker.add_middleware(AsyncIO())
dramatiq.set_broker(broker)


async def submit(job: dict[str, Any]) -> None:
    run_job.send(job)


@dramatiq.actor(actor_name="bench_run", max_retries=0, time_limit=600_000)
async def run_job(job: dict[str, Any]) -> None:
    await workload.run(job, submit)
