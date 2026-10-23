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

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories import agent_run_repo
from app.services.change_feed import ChangeEvent, run_event

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

    async def reap_stale(self) -> list[ChangeEvent]:
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

        Open consoles are told, once the caller has committed: the events
        returned are what clears a chat's "Working" and the conversation list's
        running mark, which otherwise held until something else refetched them.

        Returns:
            One `updated` run event per run reaped, for the caller to publish
            after its commit - none on the ordinary sweep, which is why the
            flow logs only when there are some.
        """
        seconds = settings.STALE_RUN_REAPED_AFTER_SECONDS
        if seconds <= 0:
            return []
        now = datetime.now(UTC)
        reaped = await agent_run_repo.fail_stale_runs(
            self.db,
            older_than=now - timedelta(seconds=seconds),
            ended_at=now,
            error=_REAPED_ERROR,
        )
        for run in reaped:
            logger.warning("stale_run_reaped", extra={"run_id": str(run.id)})
        # Built while the rows are attached; published once they are committed.
        return [run_event(run, "updated") for run in reaped]
