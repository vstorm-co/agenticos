"""Scheduled upkeep for the media agents generate (#2310)."""

import logging

from app.services.generated_media import sweep_expired_generated_media

logger = logging.getLogger(__name__)


async def sweep_generated_media() -> int:
    """Delete generated files past `GENERATED_MEDIA_RETENTION_DAYS`. Returns how many.

    The sweep opens a session per batch and commits each before the next, so it
    takes none from here.
    """
    removed = await sweep_expired_generated_media()
    if removed:
        logger.info("generated_media_swept", extra={"removed": removed})
    return removed
