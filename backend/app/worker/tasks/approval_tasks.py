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

from app.db.session import get_db_context
from app.services.approvals import ApprovalService
from app.services.channels.handback import ensure_channel_adapters

logger = logging.getLogger(__name__)


async def expire_approvals() -> int:
    """Deny by timeout every parked call past `APPROVAL_EXPIRY_HOURS`, and end its run.

    The same pass also ends runs parked on an unanswered question and runs on a
    chat surface that were decided but never continued, each in its own transaction,
    and first registers the chat adapters this worker needs to tell a chat about it.

    Returns how many approvals were expired, so a caller can say what the sweep
    found without anybody reading the logs.
    """
    # The worker registers no chat adapters of its own, and the notices these
    # sweeps spawn need one. A failure must not stop the sweeps: the notice then
    # logs that it had no adapter, and the runs are ended all the same.
    try:
        ensure_channel_adapters()
    except Exception:
        logger.warning("Approval sweep: could not register the chat adapters", exc_info=True)

    # One transaction each, so the audit lock a sweep takes last is never held
    # while the next one claims its rows.
    async with get_db_context() as db:
        expired = await ApprovalService(db).expire_stale()
    # Questions an agent asked that nobody answered park their runs the same
    # way, on their own shorter clock (#2064).
    async with get_db_context() as db:
        unanswered = await ApprovalService(db).expire_unanswered()
    # Runs a decision was recorded on and nothing continued (#2656).
    async with get_db_context() as db:
        stranded = await ApprovalService(db).end_stranded()

    if unanswered:
        logger.warning("Question sweep: %d run(s) ended with a question unanswered", unanswered)

    if stranded:
        logger.warning(
            "Stranded sweep: %d run(s) ended with a decision nothing continued", stranded
        )

    if expired:
        # Worth a warning rather than an info: each one is a decision somebody
        # was asked for and did not make, and the agent's work was thrown away.
        logger.warning("Approval sweep: %d approval(s) expired undecided", expired)
    return expired
