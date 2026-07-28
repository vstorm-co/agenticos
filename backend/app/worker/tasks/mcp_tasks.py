"""Scheduled upkeep for MCP connections.

One flow, and it exists for a failure that is otherwise found at the worst
possible moment. OAuth tokens are refreshed lazily, when a run needs one, and
that is the right place for it - no schedule renews a token more precisely than
the moment it is used. But a *refresh token* can die: the grant is withdrawn in
the provider's console, or it sits unused past its own lifetime. Nothing notices
until an agent reaches for the server mid-conversation, in front of whoever
asked the question.

This finds it first, and writes it down where the UI already looks.
"""

import logging

from prefect import flow

from app.db.session import get_db_context
from app.services.mcp_connection import sweep_oauth_connections

logger = logging.getLogger(__name__)


@flow(name="mcp-connection-sweep")
async def mcp_connection_sweep_flow() -> dict[str, int]:
    """Renew OAuth tokens near expiry; mark the connections that cannot be renewed.

    Returns the per-outcome counts so a run's result says what it found without
    anybody reading the logs.
    """
    async with get_db_context() as db:
        counts = await sweep_oauth_connections(db)

    if counts["needs_authorization"]:
        # Worth a warning rather than an info: somebody has to go and reconnect
        # it, and until they do every agent bound to that server is degraded.
        logger.warning(
            "MCP sweep: %d connection(s) need reauthorization, %d refreshed",
            counts["needs_authorization"],
            counts["refreshed"],
        )
    else:
        logger.info("MCP sweep: %s", counts)
    return counts
