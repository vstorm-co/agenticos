"""Hatchet (self-hosted hatchet-lite on our Postgres), async Python SDK.

Run:
    python -m bench.backends.hatchet_app

The engine schedules, the worker holds `slots` concurrent runs on one event loop.
`BENCH_FAIR=1` gives each run a concurrency key of its tenant with
`GROUP_ROUND_ROBIN`: no tenant holds more than half the slots, and queued runs are
taken round-robin across tenants. A run whose worker dies is reassigned when the
engine stops hearing the worker's heartbeat.
"""

import os
from datetime import timedelta
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context, Hatchet
from hatchet_sdk.runnables.types import EmptyModel
from pydantic import BaseModel

from bench import config, workload
from bench import heavy as _heavy  # noqa: F401 - the real application's import cost

hatchet = Hatchet()
FAIR = os.environ.get("BENCH_FAIR", "0") == "1"


class BenchInput(BaseModel):
    job: dict[str, Any]
    tenant: str


_concurrency = (
    ConcurrencyExpression(
        expression="input.tenant",
        max_runs=max(1, config.CONCURRENCY // 2),
        limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
    )
    if FAIR
    else None
)


@hatchet.task(
    name="bench-run",
    input_validator=BenchInput,
    concurrency=_concurrency,
    execution_timeout=timedelta(minutes=10),
    schedule_timeout=timedelta(minutes=30),
    retries=1,
)
async def run_job(input: BenchInput, ctx: Context) -> None:
    await workload.run(input.job, submit)


@hatchet.task(name="bench-sweep", on_crons=["* * * * *"])
async def sweep(input: EmptyModel, ctx: Context) -> None:
    await workload.sweep()


async def submit(job: dict[str, Any]) -> None:
    await run_job.aio_run_no_wait(BenchInput(job=job, tenant=job["tenant"]))


def main() -> None:
    worker = hatchet.worker("bench", slots=config.CONCURRENCY, workflows=[run_job, sweep])
    worker.start()


if __name__ == "__main__":
    main()
