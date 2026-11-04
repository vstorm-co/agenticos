"""Nudge a WhatsApp customer before their 24-hour window closes (#2076).

A run that waits on an approval can be answered after the window has closed, and an
answer sent then needs a template. One general message with one button, sent while the
window is still open, gives the customer a way to reopen it: a tap is a new message,
and the answer later goes out as ordinary text. `whatsapp_window.nudge_due` says who is
due; this module finds them and sends. Nothing here may affect any other send: one
customer's failure is logged and the next goes on.
"""

import logging
from datetime import datetime
from uuid import UUID

from app.db.session import get_db_context
from app.repositories import channel_bot_repo, whatsapp_customer_repo
from app.services.channel_bot import unseal_bot_token
from app.services.channels.base import ChannelChoice, PromptMessage
from app.services.channels.whatsapp import whatsapp_adapter
from app.services.channels.whatsapp_window import NUDGE_BUTTON, NUDGE_REPLY_ID, NUDGE_TEXT

logger = logging.getLogger(__name__)


async def send_due_nudges(now: datetime) -> int:
    """Send each due customer's nudge once; returns how many were sent.

    A customer is marked, and the mark committed, before anything is sent: a failed or
    interrupted send is not retried, so a customer is never nudged twice in a window.
    """
    async with get_db_context() as db:
        due = [
            (customer.id, customer.organization_id, customer.bot_id, customer.bsuid)
            for customer in await whatsapp_customer_repo.nudge_candidates(db, now=now)
        ]
    sent = 0
    for customer_id, organization_id, bot_id, bsuid in due:
        try:
            if await _nudge(customer_id, organization_id, bot_id, bsuid, now):
                sent += 1
        except Exception as failure:
            logger.warning(
                "whatsapp_nudge_failed",
                extra={"bot_id": str(bot_id), "error": type(failure).__name__},
            )
    return sent


async def _nudge(
    customer_id: UUID, organization_id: UUID, bot_id: UUID, bsuid: str, now: datetime
) -> bool:
    """Mark one customer and send their nudge; True when it was sent."""
    async with get_db_context() as db:
        won = await whatsapp_customer_repo.mark_nudged(db, customer_id=customer_id, now=now)
    if not won:
        return False
    token = await _token(bot_id, organization_id)
    if token is None:
        return False
    prompt = PromptMessage(
        platform_chat_id=bsuid,
        text=NUDGE_TEXT,
        choices=[ChannelChoice(label=NUDGE_BUTTON, value=NUDGE_REPLY_ID)],
        bot_id=str(bot_id),
        run_id=None,
    )
    await whatsapp_adapter().send_prompt(token, prompt)
    return True


async def _token(bot_id: UUID, organization_id: UUID) -> str | None:
    """The bot's token, or `None` when the bot is gone, switched off or its token cannot be read."""
    try:
        async with get_db_context() as db:
            bot = await channel_bot_repo.get_for_org(db, bot_id, organization_id=organization_id)
            return unseal_bot_token(bot) if bot is not None and bot.is_active else None
    except Exception as failure:
        logger.warning(
            "whatsapp_nudge_unsent",
            extra={"bot_id": str(bot_id), "error": type(failure).__name__},
        )
        return None
