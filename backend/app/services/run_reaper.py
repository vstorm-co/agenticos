"""Reaping runs a dead process left durably running.

A run's row is committed `running` before its model is called, so every
executing run is visible for its whole life - and a process that dies mid-run
(SIGKILL, OOM, a deploy that does not drain) leaves a row nothing will ever
finish. In-process failures cannot reach this state: `_run`'s `finally` records
a terminal status on every exception path, and an error before the opening
commit rolls the flushed row back. Only a death the process never saw coming
leaves the orphan, which is why the ceiling has to be a schedule, exactly as
the approvals queue's is.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories import agent_run_repo

logger = logging.getLogger(__name__)

# Stored on `agent_runs.error` and rendered in run history, so it is a
# controlled sentence about the run, never anything a process wrote on the way
# down (the log carries nothing extra either - the process that knew more died).
_REAPED_ERROR = (
    "The process running this run died before recording an outcome; ended by the stale-run sweep."
)


class RunReaperService:
    """Ends the runs whose process died under them."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def reap_stale(self) -> int:
        """Mark every run `running` past the ceiling as failed, and say so.

        `failed`, not `cancelled`: nobody stopped this run - the process died
        under it - and an operator filtering run history for problems is
        exactly who needs to see it. That is the opposite call from the
        approvals sweep's `cancelled`, for the opposite reason: an expired
        approval is a run that worked and was abandoned by a person; a reaped
        run is one the infrastructure failed.

        What the reap deliberately does not do:

        - **No spend is recovered.** The tokens a crashed run bought were never
          recorded anywhere a sweep could read - the ledger died with the
          process - so the row keeps the zeros it was opened with rather than
          being given a number somebody would reconcile against a bill.
        - **Nobody is notified.** The failure mail rides `finish`, which has
          the agent and its spec in hand; a sweep has neither, and a
          notification built from a bare row would name nothing actionable.
        - **Parked runs are left alone.** `awaiting_approval` has a resolver -
          the person its approval waits on - and its own sweep.

        A trigger whose conversation tail was such an orphan claims again on
        the tick after the reap: `claim_due`'s `last_run_id` join blocks only
        while the linked run is non-terminal.

        Returns:
            How many runs were reaped - zero on the ordinary sweep, which is
            why the flow logs only when it is not.
        """
        hours = settings.STALE_RUN_REAPED_AFTER_HOURS
        if hours <= 0:
            return 0
        now = datetime.now(UTC)
        reaped = await agent_run_repo.fail_stale_runs(
            self.db,
            older_than=now - timedelta(hours=hours),
            ended_at=now,
            error=_REAPED_ERROR,
        )
        for run_id in reaped:
            logger.warning("stale_run_reaped", extra={"run_id": str(run_id)})
        return len(reaped)
