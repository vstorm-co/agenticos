"""Eval runs in the worker - one flow run per eval run.

A run can take hours over a large dataset, so it is not executed in the API
process that started it: the request commits the run and its pending cases and
then submits this flow, which works through them in a process of its own and
survives the API restarting. Concurrency inside it, and across the
organization, is the worker's (:mod:`app.services.eval_run_worker`).
"""

from __future__ import annotations

import logging
from uuid import UUID

from prefect import flow
from prefect.deployments import run_deployment

from app.core.logfire_setup import setup_worker_observability
from app.core.logging import setup_logging

logger = logging.getLogger(__name__)

# "<flow-name>/<deployment-name>", registered together in `app/worker/prefect_app.py`.
_RUN_EVAL_DEPLOYMENT = "run-eval/run-eval"


async def dispatch_eval_run(eval_run_id: str, organization_id: str) -> None:
    """Submit one eval run as its own flow run, and return without waiting for it."""
    # `run_deployment` is sync-compatible: its stub unions the coroutine it
    # returns in an async context with the `FlowRun` a sync caller gets, and ty
    # cannot tell which applies. Awaiting it is correct here.
    await run_deployment(  # ty: ignore[invalid-await]
        name=_RUN_EVAL_DEPLOYMENT,
        parameters={"eval_run_id": eval_run_id, "organization_id": organization_id},
        timeout=0,
    )


@flow(name="run-eval", log_prints=True)
async def run_eval_flow(eval_run_id: str, organization_id: str) -> None:
    """Answer, score and compare every case of one eval run."""
    from app.services.eval_run_worker import EvalRunWorker

    # A flow run is its own process and ran none of the API's startup: without
    # these its logs skip the redaction and its agent runs carry no trace.
    setup_logging()
    setup_worker_observability()
    await EvalRunWorker(UUID(eval_run_id), UUID(organization_id)).run()
