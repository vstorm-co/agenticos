"""Eval suites in the worker: the minute sweep that schedules, starts and settles them.

Four steps a tick, each its own transaction, so what one commits the next can
read: queue a run of every suite whose schedule came due; start every result
that is due, as an eval run of its suite's owner; settle every result whose
eval run has ended; and move a guarded environment that follows publishes once
its guards all pass on the newest version. An eval run itself is a job of its own
(:mod:`app.worker.tasks.eval_tasks`), so a tick only writes rows and queues them.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.db.session import get_worker_db_context

if TYPE_CHECKING:
    from app.services.eval_suite import EvalSuiteService

logger = logging.getLogger(__name__)


async def check_eval_suites() -> dict[str, int]:
    """One tick of the eval suite sweep. Returns what it did, for a test or a log line.

    Each step stands alone: one that fails is logged and the next still runs, so
    a schedule that cannot fire does not also stop finished runs being settled.
    """
    from app.services import change_feed
    from app.services.eval_suite import EvalSuiteService

    # A settled result is announced to open consoles, and this process ran none
    # of the API's startup that gives the feed its Redis.
    await change_feed.connect_in_worker()
    now = datetime.now(UTC)
    steps: tuple[tuple[str, Callable[[EvalSuiteService], Awaitable[int]]], ...] = (
        ("fired", lambda service: service.fire_schedules(now=now)),
        ("started", lambda service: service.start_due(now=now)),
        ("settled", lambda service: service.settle_finished(now=now)),
        ("followed", lambda service: service.reconcile_followers()),
    )
    counts: dict[str, int] = {}
    for name, step in steps:
        try:
            async with get_worker_db_context() as db:
                counts[name] = await step(EvalSuiteService(db))
        except Exception:
            logger.exception("eval_suites_step_failed", extra={"step": name})
            counts[name] = 0
    logger.info("eval_suites_check", extra=counts)
    return counts
