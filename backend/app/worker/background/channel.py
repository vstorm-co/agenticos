"""In-process handler for channel-bot webhook events (Telegram, Slack).

Dispatched via FastAPI `BackgroundTasks` from the webhook routes so the platform
gets a fast 200 OK while routing/AI happens in the background.
"""

import logging
from typing import Any
from uuid import UUID

from app.db.session import get_db_context
from app.repositories import channel_bot_repo
from app.services.channels.base import FeedbackComment, read_feedback
from app.services.channels.feedback import ChannelFeedback
from app.services.channels.prompts import ChannelPrompts
from app.services.channels.router import ChannelMessageRouter
from app.services.channels.slack_app import SlackSurfaces

logger = logging.getLogger(__name__)


async def process_channel_event(incoming: Any) -> None:
    """Route an incoming channel event to its handler.

    Errors are logged with full traceback but never re-raised - the response to the
    platform has already been sent, and an unhandled exception here would just become
    a noisy stack trace in the API process logs.
    """
    try:
        async with get_db_context() as db:
            await ChannelMessageRouter().route(incoming, db)
    except Exception:
        logger.exception("channel_event_processing_failed")


async def process_channel_press(press: Any) -> None:
    """Decide or answer what a pressed button was offered for (#2064, #2067).

    The same bargain as a message: the platform has had its 200, so a failure is
    logged rather than raised.
    """
    try:
        async with get_db_context() as db:
            # A thumbs button rates an answer; every other button answers a prompt.
            if read_feedback(press.value) is not None:
                await ChannelFeedback(db).rate(press)
            else:
                await ChannelPrompts(db).press(press)
    except Exception:
        logger.exception("channel_press_processing_failed")


async def process_feedback_comment(comment: FeedbackComment) -> None:
    """Keep what somebody said was wrong with an answer (#2084); failures are logged."""
    try:
        async with get_db_context() as db:
            await ChannelFeedback(db).comment(comment)
    except Exception:
        logger.exception("channel_feedback_comment_failed")


async def process_slack_surface(payload: dict[str, Any], bot_id: str) -> None:
    """App Home, the assistant pane or an unfurl, for one Slack bot (#2067)."""
    try:
        async with get_db_context() as db:
            bot = await channel_bot_repo.get_for_inbound(db, UUID(bot_id))
            if bot is not None and bot.is_active:
                await SlackSurfaces(db).handle(payload, bot)
    except Exception:
        logger.exception("slack_surface_processing_failed")
