"""Scheduled upkeep for run history.

For the one state a run can be left in that nothing in-process will ever
resolve: `running` with its process dead underneath it. Everything else a run
can end in is written by the run's own `finally`; these are the ceiling for the
runs that never got one - an hourly flow for agent runs, and a minute sweep for
eval runs, which hold their organization's eval slots while they stand.
"""

import logging

from prefect import flow

from app.db.session import get_worker_db_context
from app.services.run_reaper import RunReaperService

logger = logging.getLogger(__name__)


@flow(name="stale-run-sweep")
async def stale_run_sweep_flow() -> int:
    """Fail every run left `running` past `STALE_RUN_REAPED_AFTER_HOURS`.

    On the worker context, not the pooled one: successive flow runs do not
    share an event loop, and a pooled connection made on one loop breaks
    whoever checks it out on the next - the reason `get_worker_db_context`
    exists. Returns how many runs were reaped, so a flow run's result says
    what it found without anybody reading the logs.
    """
    async with get_worker_db_context() as db:
        reaped = await RunReaperService(db).reap_stale()

    if reaped:
        # A warning rather than an info: each one is a process that died with
        # work in hand, and the spend it made is recorded nowhere.
        logger.warning("Stale-run sweep: %d run(s) reaped", reaped)
    return reaped


async def reap_abandoned_evals() -> int:
    """Fail the eval runs whose worker went silent. Returns how many.

    One of the worker's in-process sweeps (`app/worker/sweeps.py`), every
    minute: a run whose worker died waits `EVAL_ABANDONED_AFTER_MINUTES` and at
    most one tick more.
    """
    async with get_worker_db_context() as db:
        evals = await RunReaperService(db).reap_abandoned_evals()
    if evals:
        logger.warning("Abandoned-eval sweep: %d eval run(s) failed", evals)
    return evals
