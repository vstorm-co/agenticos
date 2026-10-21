"""The authoring assistant in the worker - one flow run per Improve or Verify.

A request reads up to twenty runs and calls the improver several times, which
does not belong in the API process that took the request: the request commits
the row and submits this flow, which carries it out in a process of its own
(:mod:`app.services.authoring_worker`).
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
_RUN_AUTHORING_DEPLOYMENT = "run-authoring/run-authoring"


async def dispatch_authoring_request(request_id: str, organization_id: str) -> None:
    """Submit one request as its own flow run, and return without waiting for it."""
    # `run_deployment` is sync-compatible: its stub unions the coroutine it
    # returns in an async context with the `FlowRun` a sync caller gets, and ty
    # cannot tell which applies. Awaiting it is correct here.
    await run_deployment(  # ty: ignore[invalid-await]
        name=_RUN_AUTHORING_DEPLOYMENT,
        parameters={"request_id": request_id, "organization_id": organization_id},
        timeout=0,
    )


@flow(name="run-authoring", log_prints=True)
async def run_authoring_flow(request_id: str, organization_id: str) -> None:
    """Read the evidence, ask the improver, and record what it proposes."""
    from app.services.authoring_worker import AuthoringWorker

    # A flow run is its own process and ran none of the API's startup: without
    # these its logs skip the redaction and its agent runs carry no trace.
    setup_logging()
    setup_worker_observability()
    await AuthoringWorker(UUID(request_id), UUID(organization_id)).run()
