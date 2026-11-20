"""The worker entry for the one queued proposal build of a reviewed demonstration."""

from app.db.session import get_db_context
from app.worker.jobs import BuildTeachingProposal

from ._service import BrowserTeachingService


async def build_teaching_proposal(job: BuildTeachingProposal) -> None:
    """Build it in one transaction; the service rechecks authority, state and budget first."""
    async with get_db_context() as db:
        await BrowserTeachingService(db, None).build_proposal(
            job.organization_id, job.session_id, job.source_hash
        )
