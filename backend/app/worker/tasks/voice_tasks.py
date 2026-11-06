"""Scheduled upkeep for voice calls (#54)."""

import logging

from app.db.session import get_worker_db_context
from app.services.voice import VoiceCallReaper
from app.worker.jobs import DialPhone

logger = logging.getLogger(__name__)


async def reap_voice_calls() -> int:
    """Hang up calls a dead worker left on the provider's bill. Returns how many."""
    from app.services.telephony.runtime import reap

    reaped = await VoiceCallReaper(get_worker_db_context).reap()
    reaped += await reap(sessions=get_worker_db_context)
    if reaped:
        logger.warning("Voice sweep: %d call(s) hung up", reaped)
    return reaped


async def dial_phone(payload: DialPhone) -> None:
    from app.services.telephony.runtime import dial

    await dial(payload.call_id)


async def end_phone(payload: DialPhone) -> None:
    from app.services.telephony.provider import TwilioPhoneProvider
    from app.services.telephony.runtime import end_media

    await end_media(payload.call_id, provider=TwilioPhoneProvider(), sessions=get_worker_db_context)
