"""Scheduled upkeep for the approvals queue.

One flow, for a queue that otherwise only grows. A tool call parked on a human
waits indefinitely: nothing in a request path can expire it, because the whole
point is that no request is coming. So the ceiling has to be a schedule.

What it protects is not the queue's length but the run behind each row. A parked
run sits in `awaiting_approval` until somebody decides, and an approval nobody
decides is a run that is neither finished nor going to be - which is what the
dashboard's oldest-waiting age inherits, and what run history shows for ever.
"""

import logging

from prefect import flow

from app.db.session import get_db_context
from app.services.approvals import ApprovalService

logger = logging.getLogger(__name__)


@flow(name="approval-expiry-sweep")
async def approval_expiry_sweep_flow() -> int:
    """Deny by timeout every parked call past `APPROVAL_EXPIRY_HOURS`, and end its run.

    Returns how many approvals were expired, so a flow run's result says what it
    found without anybody reading the logs.
    """
    async with get_db_context() as db:
        expired = await ApprovalService(db).expire_stale()

    if expired:
        # Worth a warning rather than an info: each one is a decision somebody
        # was asked for and did not make, and the agent's work was thrown away.
        logger.warning("Approval sweep: %d approval(s) expired undecided", expired)
    return expired
