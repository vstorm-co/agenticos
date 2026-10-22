"""Agent runs the API queued, and the scheduled upkeep for run history.

For the one state a run can be left in that nothing in-process will ever
resolve: `running` with its process dead underneath it. Everything else a run
can end in is written by the run's own `finally`; these are the ceiling for the
runs that never got one - an hourly sweep for agent runs, and a minute sweep for
eval runs, which hold their organization's eval slots while they stand.
"""

import logging

from app.db.session import get_worker_db_context
from app.schemas.agent import AgentRunResult
from app.services.api_runs import ApiRunService
from app.services.run_reaper import RunReaperService
from app.worker.jobs import RunAgent

logger = logging.getLogger(__name__)


async def reap_stale_runs() -> int:
    """Fail every run left `running` past `STALE_RUN_REAPED_AFTER_HOURS`.

    Returns how many runs were reaped, so a caller can say what the sweep
    found without anybody reading the logs.
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

    Scheduled every minute (`app/worker/schedules.py`): a run whose worker died
    waits `EVAL_ABANDONED_AFTER_MINUTES` and at most one tick more.
    """
    async with get_worker_db_context() as db:
        evals = await RunReaperService(db).reap_abandoned_evals()
    if evals:
        logger.warning("Abandoned-eval sweep: %d eval run(s) failed", evals)
    return evals


async def run_agent(job: RunAgent) -> AgentRunResult:
    """An asynchronous API run: the synchronous call, made by the worker (`app.services.api_runs`)."""
    async with get_worker_db_context() as db:
        return await ApiRunService(db).run(job)
