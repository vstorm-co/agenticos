"""Transactional improvement transitions and recovery of queued child completions."""

from app.db.session import get_worker_db_context
from app.worker.jobs import AdvanceImprovement


async def advance_improvement(job: AdvanceImprovement) -> None:
    from app.services.improvement_pipeline import ImprovementPipelineService

    async with get_worker_db_context() as db:
        await ImprovementPipelineService(db).advance(job.run_id, job.organization_id)


async def sweep_improvements() -> int:
    from app.services.improvement_pipeline import ImprovementPipelineService

    async with get_worker_db_context() as db:
        return await ImprovementPipelineService(db).sweep()
