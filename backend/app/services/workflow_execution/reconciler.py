"""The backstop for queued or interrupted workflow dispatch work.

Structurally `app.services.run_reaper.RunReaperService` applied to three
different shapes of stranded row, all on the same "died before it could
finish" family the dispatcher's own transaction boundaries exist to make
findable:

- **A claim nobody ever recorded an attempt for.** The crash window between
  phase 1 (the claim commits) and phase 2 (the `in_flight` attempt commits).
  Nothing unsafe happened - no handler ever ran - so this is safe to reclaim
  exactly like a fresh `pending` row.
- **An `in_flight` attempt nobody ever settled.** The crash window between
  phase 2 and phase 4. `app.services.workflow_execution.dispatcher.
  resolve_orphaned_attempt` is the one place that decides what to do about
  it, shared with `begin_attempt`'s own inline check for the same shape.
- **A decided approval nobody woke the workflow for.** `ApprovalService.decide`
  queues the direct wake with `spawn_after_commit`; if that trigger is lost
  (a worker restart between the decision committing and the task actually
  starting), this is what finds the same shape from the data alone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import DispatchOutbox, DispatchOutboxStatus, NodeAttemptStatus
from app.repositories import workflow_run as workflow_run_repo
from app.services.workflow_execution import dispatcher

logger = logging.getLogger(__name__)


def _lease_expired(outbox: DispatchOutbox | None, *, at: datetime) -> bool:
    """Whether `outbox` is still a claim nobody has renewed or closed by `at`."""
    return (
        outbox is not None
        and outbox.status == DispatchOutboxStatus.CLAIMED.value
        and outbox.lease_expires_at is not None
        and outbox.lease_expires_at < at
    )


class WorkflowReconcilerService:
    """Finds and resolves stranded workflow-execution rows."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def stale_claims(self, *, limit: int = 100) -> list[tuple[UUID, UUID]]:
        """`(workflow_run_id, node_run_id)` pairs whose claim expired with no
        attempt ever made. Read-only: the caller (`app.worker.tasks.
        workflow_tasks.workflow_reconcile_flow`) re-triggers
        `workflow-dispatch-node` for each, which performs the actual claim -
        keeping exactly one code path responsible for the compare-and-swap.
        """
        rows = await workflow_run_repo.list_stale_claims(
            self.db, before=datetime.now(UTC), limit=limit
        )
        return [(row.workflow_run_id, row.node_run_id) for row in rows]

    async def resolve_orphaned_attempts(self, *, limit: int = 100) -> int:
        """Settle every `in_flight` attempt whose owning lease expired.

        Returns how many were resolved - zero on the ordinary sweep.
        """
        attempts = await workflow_run_repo.list_orphaned_in_flight(
            self.db, before=datetime.now(UTC), limit=limit
        )
        resolved = 0
        for attempt in attempts:
            scanned = await workflow_run_repo.get_node_run_by_id(self.db, attempt.node_run_id)
            if scanned is None:
                continue
            # The dispatcher's own lock order - run, node run, outbox - so a
            # sweep and a dispatch tick for the same node queue behind each
            # other instead of deadlocking.
            run = await workflow_run_repo.get_run_by_id_for_update(self.db, scanned.workflow_run_id)
            node_run = await workflow_run_repo.get_node_run_by_id_for_update(
                self.db, attempt.node_run_id
            )
            outbox = await workflow_run_repo.get_outbox_for_node_run_for_update(
                self.db, node_run_id=attempt.node_run_id
            )
            # Everything the scan saw is re-checked under those locks: another
            # worker may have reclaimed the row (a fresh lease), resolved the
            # attempt itself (`begin_attempt`'s inline check) or closed the row
            # (a cancel) since. Resolving on the scan's word would mark a live
            # claim done and leave its holder dispatching a node that must not
            # run again.
            fresh = await workflow_run_repo.get_attempt(self.db, attempt.id)
            if (
                run is None
                or node_run is None
                or fresh is None
                or fresh.status != NodeAttemptStatus.IN_FLIGHT.value
                or not _lease_expired(outbox, at=datetime.now(UTC))
            ):
                continue
            await dispatcher.resolve_orphaned_attempt(
                self.db, run=run, node_run=node_run, attempt=fresh, outbox=outbox
            )
            resolved += 1
            logger.warning(
                "workflow_attempt_reclaimed",
                extra={"node_run_id": str(node_run.id), "attempt_id": str(fresh.id)},
            )
        return resolved

    async def wake_stale_approval_decisions(self, *, limit: int = 100) -> int:
        """Insert the backstop dispatch row for every decided approval whose
        direct wake was lost.

        Each insert is tolerant of losing a race to that direct wake: the
        partial unique index on live `dispatch_outbox` rows refuses a second
        one for the same `NodeRun`, read back here as "already dispatched"
        inside a savepoint rather than as a failure.
        """
        node_runs = await workflow_run_repo.list_stale_approval_waits(self.db, limit=limit)
        woken = 0
        for node_run in node_runs:
            run = await workflow_run_repo.get_run_by_id_for_update(
                self.db, node_run.workflow_run_id
            )
            if run is None:
                continue
            try:
                async with self.db.begin_nested():
                    await workflow_run_repo.create_outbox(
                        self.db,
                        organization_id=run.organization_id,
                        workflow_run_id=run.id,
                        node_run_id=node_run.id,
                        available_at=datetime.now(UTC),
                    )
            except IntegrityError:
                continue
            woken += 1
        return woken
