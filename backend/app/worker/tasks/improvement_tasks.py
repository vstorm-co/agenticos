"""Transactional improvement transitions and recovery of queued child completions."""

from app.db.session import get_worker_db_context
from app.worker.jobs import AdvanceImprovement


async def advance_improvement(job: AdvanceImprovement) -> None:
    from app.repositories import improvement_repo
    from app.schemas.change_event import ChangeEvent
    from app.services.change_feed import publish
    from app.services.improvement_pipeline import ImprovementPipelineService

    async with get_worker_db_context() as db:
        row = await improvement_repo.get_run(db, job.run_id, organization_id=job.organization_id)
        before = None if row is None else (row.status, row.stage, row.iteration)
        await ImprovementPipelineService(db).advance(job.run_id, job.organization_id)
        after = None if row is None else (row.status, row.stage, row.iteration)
        agent_id = row.agent_id if row else None
    if agent_id is not None and before != after:
        await publish(
            ChangeEvent(
                organization_id=job.organization_id,
                resource="agent",
                id=agent_id,
                action="updated",
                surface="system",
                actor_user_id=None,
                actor_name=None,
            )
        )


async def sweep_improvements() -> int:
    from app.services.improvement_pipeline import ImprovementPipelineService

    async with get_worker_db_context() as db:
        return await ImprovementPipelineService(db).sweep()
