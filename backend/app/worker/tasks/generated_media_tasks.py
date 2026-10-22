"""Scheduled upkeep for the media agents generate (#2310)."""

import logging

from app.db.session import get_worker_db_context
from app.services.generated_media import GeneratedMediaService

logger = logging.getLogger(__name__)


async def sweep_generated_media() -> int:
    """Delete generated files past `GENERATED_MEDIA_RETENTION_DAYS`. Returns how many."""
    async with get_worker_db_context() as db:
        removed = await GeneratedMediaService(db).sweep_expired()
    if removed:
        logger.info("generated_media_swept", extra={"removed": removed})
    return removed
