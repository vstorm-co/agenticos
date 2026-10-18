"""Background worker entry for shop agent jobs (D3 B62/B75)."""

from __future__ import annotations

import logging
from uuid import UUID

from prefect import flow

from app.core.background import spawn
from app.db.session import get_worker_db_context
from app.repositories import shop_agent_background_job as job_repo
from app.services.shop_background_agent_runner import run_shop_background_job as execute_job

logger = logging.getLogger(__name__)


async def run_shop_background_job_task(*, job_id: UUID) -> None:
    async with get_worker_db_context() as db:
        row = await execute_job(db, job_id)
    logger.info("Shop background job finished id=%s status=%s", job_id, row.status)


async def run_due_shop_digest_jobs(db) -> dict[str, int]:
    """Queue due digest rows via background task runner (B75)."""
    queued = 0
    due = await job_repo.list_due_digest_jobs(db, limit=20)
    for row in due:
        spawn(
            run_shop_background_job_task(job_id=row.id),
            name=f"shop_digest_job:{row.id}",
        )
        queued += 1
    logger.info("Queued %s shop digest background jobs", queued)
    return {"queued": queued}


@flow(name="shop-agent-background-digest")
async def shop_agent_background_digest_flow() -> dict[str, int]:
    async with get_worker_db_context() as db:
        try:
            return await run_due_shop_digest_jobs(db)
        except Exception:
            logger.exception("Shop agent background digest flow failed")
            raise
