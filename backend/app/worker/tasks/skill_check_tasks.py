"""Carrying skill checks on from one stage to the next."""

from app.db.session import get_worker_db_context
from app.worker.jobs import AdvanceSkillCheck


async def advance_skill_check(job: AdvanceSkillCheck) -> None:
    from app.services.skill_check import SkillCheckService

    async with get_worker_db_context() as db:
        await SkillCheckService(db).advance(job.check_id, job.organization_id)


async def sweep_skill_checks() -> int:
    from app.services.skill_check import SkillCheckService

    async with get_worker_db_context() as db:
        return await SkillCheckService(db).sweep()
