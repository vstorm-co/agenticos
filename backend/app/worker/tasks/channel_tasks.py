"""Scheduled upkeep for channel bots."""

import logging

from app.db.session import get_db_context
from app.services.channels.discord_roles import sweep_discord_roles

logger = logging.getLogger(__name__)


async def sync_discord_roles() -> dict[str, int]:
    """Reconcile everybody a Discord role placed with the roles they hold now (#2569)."""
    counts = await sweep_discord_roles(get_db_context)
    if counts["unreadable"]:
        logger.warning("Discord role sync: %d person(s) could not be checked", counts["unreadable"])
    if counts["failed"]:
        logger.error("Discord role sync: %d person(s) failed", counts["failed"])
    return counts
