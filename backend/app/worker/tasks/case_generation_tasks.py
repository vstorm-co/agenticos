"""Case generation in the worker - one job per generation.

The generator answers in minutes, and an automated improvement waits on the
result, so the request queues this job with the generation instead of running
it in the API process, where a restart lost it without a trace
(:mod:`app.services.case_generation.worker`).
"""

from app.worker.jobs import GenerateCases


async def generate_cases(job: GenerateCases) -> None:
    """Draft the generation's cases, and accept them when it was asked to."""
    from app.services.case_generation.worker import CaseGenerationWorker

    await CaseGenerationWorker(job.generation_id, job.organization_id).run()


async def settle_lost_generation(job: GenerateCases, reason: str) -> None:
    """A generation whose job ended for good without the handler ending it."""
    del reason
    from app.services.case_generation.worker import settle_lost

    await settle_lost(job.generation_id, job.organization_id)
