"""Scheduled upkeep for run history.

One flow, for the one state a run can be left in that nothing in-process will
ever resolve: `running` with its process dead underneath it. Everything else a
run can end in is written by the run's own `finally`; this is the ceiling for
the runs that never got one.
"""

import logging

from prefect import flow

from app.db.session import get_db_context
from app.services.run_reaper import RunReaperService

logger = logging.getLogger(__name__)


@flow(name="stale-run-sweep")
async def stale_run_sweep_flow() -> int:
    """Fail every run left `running` past `STALE_RUN_REAPED_AFTER_HOURS`.

    Returns how many runs were reaped, so a flow run's result says what it
    found without anybody reading the logs.
    """
    async with get_db_context() as db:
        reaped = await RunReaperService(db).reap_stale()

    if reaped:
        # A warning rather than an info: each one is a process that died with
        # work in hand, and the spend it made is recorded nowhere.
        logger.warning("Stale-run sweep: %d run(s) reaped", reaped)
    return reaped
