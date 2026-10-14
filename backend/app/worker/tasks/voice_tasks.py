"""Scheduled upkeep for voice calls (#54)."""

import logging

from prefect import flow

from app.db.session import get_worker_db_context
from app.services.voice import VoiceCallReaper

logger = logging.getLogger(__name__)


@flow(name="voice-call-sweep")
async def voice_call_sweep_flow() -> int:
    """Hang up calls a dead worker left on the provider's bill. Returns how many."""
    async with get_worker_db_context() as db:
        reaped = await VoiceCallReaper(db).reap()
    if reaped:
        logger.warning("Voice sweep: %d call(s) hung up", reaped)
    return reaped
