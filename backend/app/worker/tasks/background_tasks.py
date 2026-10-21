"""Upkeep for the job queue itself (#2219)."""

import logging
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.db.session import get_db_context
from app.repositories import background_job as background_job_repo

logger = logging.getLogger(__name__)

_BATCH = 5000
"""Rows deleted per statement, so a first sweep over months of history holds no lock for long."""


async def sweep_background_jobs() -> int:
    """Forget finished jobs older than `BACKGROUND_JOB_RETENTION_DAYS`. Answers how many went.

    A minute sweep alone is several thousand rows a day, and the panel only
    ever needs the recent past. Queued and running jobs are never touched.
    """
    cutoff = datetime.now(UTC) - timedelta(days=settings.BACKGROUND_JOB_RETENTION_DAYS)
    removed = 0
    while True:
        async with get_db_context() as db:
            batch = await background_job_repo.delete_finished_before(
                db, cutoff=cutoff, limit=_BATCH
            )
        removed += batch
        if batch < _BATCH:
            break
    if removed:
        logger.info("background_jobs_swept", extra={"removed": removed})
    return removed
