"""The minute-scale sweeps, run inside the worker's own process (#2213).

Prefect runs every flow run as a new Python process that imports the whole
application. For the work that ticks every minute - the trigger heartbeat, the
portal poll, notification delivery, the sync check - that import was the whole
cost of a tick that nearly always found nothing to do, and on the production
host it took longer than the minute between ticks: four processes were always
importing, and runs queued faster than they finished.

So these are plain loops in the process that serves the deployments, where the
application is already imported. Each sweep runs one tick at a time - a slow
tick delays its next, it never overlaps it - and a tick that raises is logged
and tried again on the next interval rather than ending the loop. The sweeps
start spread across their interval, so they do not all wake at once.

Work that is heavy, retried or must outlive the process stays a Prefect flow
run: a sweep that finds such work submits it (`run_deployment`), it does not do
it here.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.clients.redis import RedisClient
from app.services import worker_heartbeat

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Sweep:
    """One recurring tick: what it is called, how often, and what it does."""

    name: str
    every_seconds: float
    tick: Callable[[], Awaitable[object]]


async def run_sweeps(sweeps: Sequence[Sweep], redis: RedisClient) -> None:
    """Run every sweep until cancelled, each started a share of its interval after the last."""
    async with asyncio.TaskGroup() as group:
        for index, sweep in enumerate(sweeps):
            group.create_task(
                keep_sweeping(sweep, redis, delay=sweep.every_seconds * index / len(sweeps)),
                name=f"sweep:{sweep.name}",
            )


async def keep_sweeping(sweep: Sweep, redis: RedisClient, *, delay: float) -> None:
    """Tick `sweep` every `every_seconds`, measured from the start of each tick."""
    await asyncio.sleep(delay)
    while True:
        started = time.monotonic()
        try:
            await sweep.tick()
        except Exception:
            logger.exception("sweep_failed", extra={"sweep": sweep.name})
        else:
            try:
                await worker_heartbeat.record(redis, sweep.name, datetime.now(UTC))
            except Exception:
                # The health probe will say the sweep stopped, which it did not;
                # better that than stopping it over a status line.
                logger.warning(
                    "sweep_heartbeat_unrecorded", extra={"sweep": sweep.name}, exc_info=True
                )
        await asyncio.sleep(max(0.0, sweep.every_seconds - (time.monotonic() - started)))
