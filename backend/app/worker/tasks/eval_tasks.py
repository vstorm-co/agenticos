"""Eval runs in the worker - one job per eval run.

A run can take hours over a large dataset, so it is not executed in the API
process that started it: the request queues this job with the run and its
pending cases, and the worker works through them and survives the API
restarting. Concurrency inside it, and across the organization, is the
worker's (:mod:`app.services.eval_run_worker`).
"""

from app.db.session import get_worker_db_context
from app.services.run_reaper import RunReaperService
from app.worker.jobs import RunEval


async def run_eval(job: RunEval) -> None:
    """Answer, score and compare every case of one eval run."""
    from app.services.eval_run_worker import EvalRunWorker

    await EvalRunWorker(job.eval_run_id, job.organization_id).run()


async def settle_lost_eval(job: RunEval, why: str) -> None:
    """An eval run whose job ended for good - withdrawn, timed out or its worker dead."""
    async with get_worker_db_context() as db:
        await RunReaperService(db).settle_lost_eval(
            job.eval_run_id, organization_id=job.organization_id, why=why
        )
