"""Drafting a case's keys in the worker - one job per draft.

A long reference answer can keep the key extractor busy longer than a request
may wait behind a proxy, so the request queues this job with the draft
(:mod:`app.services.case_key_draft`).
"""

import logging
from datetime import UTC, datetime, timedelta

from app.db.session import get_worker_db_context
from app.worker.jobs import ExtractCaseKeys

logger = logging.getLogger(__name__)


async def extract_case_keys(job: ExtractCaseKeys) -> None:
    """List the draft's keys from its case's reference answer."""
    from app.services.case_key_draft import extract_case_keys as extract

    await extract(job.draft_id, job.organization_id)


async def settle_lost_draft(job: ExtractCaseKeys, reason: str) -> None:
    """A draft whose job ended for good without the handler ending it."""
    del reason
    from app.services.case_key_draft import settle_lost

    await settle_lost(job.draft_id, job.organization_id)


async def expire_case_key_drafts() -> int:
    """Delete drafts nobody used or dismissed within `KEY_DRAFT_RETENTION_DAYS`. Returns how many."""
    from app.db.models.case_key_draft import KEY_DRAFT_RETENTION_DAYS
    from app.repositories import case_key_draft_repo

    cutoff = datetime.now(UTC) - timedelta(days=KEY_DRAFT_RETENTION_DAYS)
    async with get_worker_db_context() as db:
        removed = await case_key_draft_repo.delete_expired(db, created_before=cutoff)
    if removed:
        logger.info("case_key_drafts_expired", extra={"removed": removed})
    return removed
