"""Scheduled upkeep for MCP connections.

One flow, and it exists for a failure that is otherwise found at the worst
possible moment. OAuth tokens are refreshed lazily, when a run needs one, and
that is the right place for it - no schedule renews a token more precisely than
the moment it is used. But a *refresh token* can die: the grant is withdrawn in
the provider's console, or it sits unused past its own lifetime. Nothing notices
until an agent reaches for the server mid-conversation, in front of whoever
asked the question.

This finds it first, and writes it down where the UI already looks.

The same sweep dials every organization server (#2100): a server that stopped
answering is otherwise found the same way, by an agent mid-conversation, and an
outage is something its managers are told about rather than something they
discover.
"""

import logging

from app.db.session import get_db_context
from app.services.mcp_connection import check_organization_servers, sweep_oauth_connections

logger = logging.getLogger(__name__)


async def sweep_mcp_connections() -> dict[str, int]:
    """Renew OAuth tokens near expiry, mark those that cannot be, and check servers answer.

    Returns the per-outcome counts so a caller can say what the sweep found
    without anybody reading the logs.
    """
    async with get_db_context() as db:
        counts = await sweep_oauth_connections(db)
    # Its own transaction, after the renewals have committed: a server whose
    # token was just refreshed is dialled with the new one.
    async with get_db_context() as db:
        reached = await check_organization_servers(db)
    if reached["unreachable"]:
        logger.warning("MCP check: %d organization server(s) not answering", reached["unreachable"])

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
    return {**counts, **reached}
