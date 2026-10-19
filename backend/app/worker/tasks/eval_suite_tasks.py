"""Eval suites in the worker: the minute sweep that schedules, starts and settles them.

Three steps a tick, each its own transaction, so what one commits the next can
read: queue a run of every suite whose schedule came due; start every result
that is due, as an eval run of its suite's owner; settle every result whose
eval run has ended. An eval run itself is a flow run of its own
(:mod:`app.worker.tasks.eval_tasks`), so a tick only writes rows and submits.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.db.session import get_worker_db_context

logger = logging.getLogger(__name__)


async def check_eval_suites() -> dict[str, int]:
    """One tick of the eval suite sweep. Returns what it did, for a test or a log line."""
    from app.services import change_feed
    from app.services.eval_suite import EvalSuiteService

    # A settled result is announced to open consoles, and this process ran none
    # of the API's startup that gives the feed its Redis.
    await change_feed.connect_in_worker()
    now = datetime.now(UTC)
    async with get_worker_db_context() as db:
        fired = await EvalSuiteService(db).fire_schedules(now=now)
    async with get_worker_db_context() as db:
        started = await EvalSuiteService(db).start_due(now=now)
    async with get_worker_db_context() as db:
        settled = await EvalSuiteService(db).settle_finished(now=datetime.now(UTC))
    counts = {"fired": fired, "started": started, "settled": settled}
    logger.info("eval_suites_check", extra=counts)
    return counts
