"""Scheduled upkeep for organization invitations.

One flow, for rows that otherwise never reach their promised state. An
invitation nobody clicks is exactly the one no request path ever touches, so
`EXPIRED` can only be written on a schedule - the same reasoning as the
approval sweep. Until this ran, a stale invitation sat `pending` for ever and
the pending list kept offering it.
"""

import logging

from prefect import flow

from app.db.session import get_db_context
from app.services.invitation import InvitationService

logger = logging.getLogger(__name__)


@flow(name="invitation-expiry-sweep")
async def invitation_expiry_sweep_flow() -> int:
    """Mark every PENDING invitation past `expires_at` as EXPIRED.

    Returns how many invitations were expired, so a flow run's result says
    what it found without anybody reading the logs.
    """
    async with get_db_context() as db:
        expired = await InvitationService(db).expire_stale()

    if expired:
        logger.info("Invitation sweep: %d invitation(s) expired unaccepted", expired)
    return expired
