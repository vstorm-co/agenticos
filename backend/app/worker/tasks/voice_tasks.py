"""Scheduled upkeep for voice calls (#54)."""

import logging

from app.db.session import get_worker_db_context
from app.services.voice import VoiceCallReaper

logger = logging.getLogger(__name__)


async def reap_voice_calls() -> int:
    """Hang up calls a dead worker left on the provider's bill. Returns how many."""
    reaped = await VoiceCallReaper(get_worker_db_context).reap()
    if reaped:
        logger.warning("Voice sweep: %d call(s) hung up", reaped)
    return reaped
