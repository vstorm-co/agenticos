"""Drafting a case's keys in the worker - one job per draft.

A long reference answer can keep the key extractor busy longer than a request
may wait behind a proxy, so the request queues this job with the draft
(:mod:`app.services.case_key_draft`).
"""

from app.worker.jobs import ExtractCaseKeys


async def extract_case_keys(job: ExtractCaseKeys) -> None:
    """List the draft's keys from its case's reference answer."""
    from app.services.case_key_draft import extract_case_keys as extract

    await extract(job.draft_id, job.organization_id)


async def settle_lost_draft(job: ExtractCaseKeys, reason: str) -> None:
    """A draft whose job ended for good without the handler ending it."""
    del reason
    from app.services.case_key_draft import settle_lost

    await settle_lost(job.draft_id, job.organization_id)
