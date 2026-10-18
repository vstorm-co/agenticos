"""Prefect 3 `serve` - how AgenticOS runs background work today.

Run:
    python -m bench.backends.prefect_serve

Each submission is `run_deployment(..., timeout=0)`; the runner polls the server and
starts every flow run as a new `python -m prefect.engine` process, which imports this
module - and with it the application. `BENCH_PREFECT_LIMIT` is the runner's ceiling
on concurrent runs (production: 5). The sweep is an interval-scheduled deployment.
"""

import asyncio
import os
from datetime import timedelta
from typing import Any

from prefect import aserve, flow
from prefect.client.schemas.schedules import IntervalSchedule
from prefect.deployments import run_deployment

from bench import config, workload
from bench import heavy as _heavy  # noqa: F401 - the real application's import cost

LIMIT = int(os.environ.get("BENCH_PREFECT_LIMIT", "5"))


async def submit(job: dict[str, Any]) -> None:
    await run_deployment(  # ty: ignore[invalid-await]
        name="bench-run/bench-run", parameters={"job": job}, timeout=0
    )


@flow(name="bench-run")
async def bench_run(job: dict[str, Any]) -> None:
    await workload.run(job, submit)


@flow(name="bench-sweep")
async def bench_sweep() -> None:
    await workload.sweep()


async def main() -> None:
    run = await bench_run.ato_deployment(name="bench-run")
    tick = await bench_sweep.ato_deployment(
        name="bench-sweep",
        schedules=[IntervalSchedule(interval=timedelta(seconds=config.SWEEP_SECONDS))],
    )
    await aserve(run, tick, limit=LIMIT)


if __name__ == "__main__":
    asyncio.run(main())
