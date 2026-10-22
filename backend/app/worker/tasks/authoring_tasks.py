"""The authoring assistant in the worker - one job per Improve or Verify.

A request reads up to twenty runs and calls the improver several times, which
does not belong in the API process that took the request: the request queues
this job with the row, and the worker carries it out
(:mod:`app.services.authoring_worker`).
"""

from app.worker.jobs import RunAuthoring


async def run_authoring(job: RunAuthoring) -> None:
    """Read the evidence, ask the improver, and record what it proposes."""
    from app.services.authoring_worker import AuthoringWorker

    await AuthoringWorker(job.request_id, job.organization_id).run()
