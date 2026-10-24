"""Reaping runs a dead process left durably running.

A run's row is committed `running` before its model is called, so every
executing run is visible for its whole life - and a process that dies mid-run
(SIGKILL, OOM, a deploy that does not drain) leaves a row nothing will ever
finish. In-process failures cannot reach this state: `_run`'s `finally` records
a terminal status on every exception path, and an error before the opening
commit rolls the flushed row back. Only a death the process never saw coming
leaves the orphan, which is why the ceiling has to be a schedule, exactly as
the approvals queue's is.

An eval run and an authoring request are closed sooner: the worker hands each
job that ended for good - withdrawn from the queue, timed out, its process
dead - to the settlers here, so nothing waits for a sweep's window.
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories import agent_run_repo, authoring_repo, eval_run_repo
from app.services.change_feed import ChangeEvent, run_event
from app.worker.jobs import RUN_EVAL, SettleLater

logger = logging.getLogger(__name__)

# Stored on `agent_runs.error` and rendered in run history, so it is a
# controlled sentence about the run, never anything a process wrote on the way
# down (the log carries nothing extra either - the process that knew more died).
_REAPED_ERROR = (
    "The process running this run died before recording an outcome; ended by the stale-run sweep."
)

_LOCK_NOT_AVAILABLE = "55P03"

# What `background_job_repo.unsettled_ends` answers for a queued job an
# administrator withdrew: its status, since nothing ran to write an error.
_WITHDRAWN = "cancelled"

# Stored on the run and the request and shown to whoever started them, so a
# controlled sentence: the job's own last error is the worker's, for the log.
_EVAL_JOB_ENDED = "This eval's job ended before the run did. Run it again."
_AUTHORING_WITHDRAWN = "The request was cancelled before it started. Try again."
_AUTHORING_JOB_ENDED = "The assistant stopped without finishing. Try again."


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

    async def reap_abandoned_evals(self) -> int:
        """Fail every eval run whose worker stopped moving, and free its slots.

        A worker that dies leaves its run live and its claimed cases running,
        and the organization's eval concurrency counts running cases - so
        without this, a crash would hold those slots for good. A queued run is
        failed once no job is left to run it, and an attempt a dead worker left
        running under a run that has ended is failed after the same window.

        Returns:
            How many runs and attempts were closed.
        """
        minutes = settings.EVAL_ABANDONED_AFTER_MINUTES
        if minutes <= 0:
            return 0
        now = datetime.now(UTC)
        idle_since = now - timedelta(minutes=minutes)
        runs = await eval_run_repo.fail_abandoned(
            self.db, idle_since=idle_since, job_kind=RUN_EVAL.kind, now=now
        )
        attempts = await eval_run_repo.close_orphaned_attempts(self.db, ended_before=idle_since)
        return runs + attempts

    async def settle_lost_eval(self, eval_run_id: UUID, *, organization_id: UUID, why: str) -> None:
        """Close an eval run whose job ended for good while the run was still live.

        A job withdrawn from the queue cancels its run: none of it ran. Any other
        end - a timeout, its worker dying, the handler failing - fails the run
        with its unfinished attempts, which frees the eval slots they held. A run
        its worker closed first keeps its outcome.
        """
        now = datetime.now(UTC)
        if why == _WITHDRAWN:
            closed = await eval_run_repo.cancel_live(
                self.db, eval_run_id, organization_id=organization_id, now=now
            )
        else:
            closed = await eval_run_repo.fail_live(
                self.db,
                eval_run_id,
                organization_id=organization_id,
                now=now,
                error=_EVAL_JOB_ENDED,
            )
        if closed:
            logger.warning("eval_run_job_lost", extra={"eval_run_id": str(eval_run_id), "why": why})

    async def settle_lost_authoring(
        self, request_id: UUID, *, organization_id: UUID, why: str
    ) -> None:
        """Fail an authoring request whose job ended for good before the request did.

        Raises:
            SettleLater: A worker still holds the request; it is not waited on,
                and the rescuer settles it on a later pass.
        """
        try:
            failed = await authoring_repo.fail_unfinished(
                self.db,
                request_id,
                organization_id=organization_id,
                error=_AUTHORING_WITHDRAWN if why == _WITHDRAWN else _AUTHORING_JOB_ENDED,
                now=datetime.now(UTC),
            )
        except DBAPIError as refused:
            if getattr(refused.orig, "sqlstate", None) != _LOCK_NOT_AVAILABLE:
                raise
            raise SettleLater("a worker still holds the authoring request") from None
        if failed:
            logger.warning(
                "authoring_request_job_lost", extra={"request_id": str(request_id), "why": why}
            )
