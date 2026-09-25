"""The direct wake: an approval decision tells a parked `NodeRun` to resume.

`ApprovalService.decide` is the **existing**, unchanged surface - a workflow
run has no chat socket for anyone to click "resume" in, so nothing about how
a human decides an approval changes. What this module is: the one thing
#1788 adds once that decision commits, queued with `spawn_after_commit`
because it must not observe the transaction that produced it, and must not
hold anything belonging to it either - only ids, which is all a fresh
session needs to find its way back to the `NodeRun` waiting on it.

Best-effort by design. If this trigger is lost (the process dies before the
task starts), `app.services.workflow_execution.reconciler.
WorkflowReconcilerService.wake_stale_approval_decisions` finds the same shape
from the data alone, on its own schedule - the backstop the design calls for
rather than a second guarantee this module has to make itself.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.db.models.agent_run import ApprovalStatus
from app.db.models.workflow_run import (
    NodeRun,
    NodeRunStatus,
    WaitingReason,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.db.session import get_worker_db_context
from app.repositories import agent_run as agent_run_repo
from app.repositories import workflow_run as workflow_run_repo

logger = logging.getLogger(__name__)


def still_waiting_on(run: WorkflowRun, node_run: NodeRun, *, agent_run_id: UUID | None) -> bool:
    """Whether `node_run`, read under `run`'s lock, is still parked on `agent_run_id`.

    Both wakes find the node with an unlocked read and insert its outbox row
    only once they hold the run's lock; anything the node did in between -
    the other wake dispatched it, it succeeded, it re-parked on a different
    agent run - must stop the insert.
    """
    return (
        not WorkflowRunStatus(run.status).is_terminal
        and node_run.status == NodeRunStatus.WAITING.value
        and node_run.waiting_reason == WaitingReason.APPROVAL.value
        and agent_run_id is not None
        and node_run.waiting_agent_run_id == agent_run_id
    )


async def wake_after_approval_decision(agent_run_id: UUID, *, organization_id: UUID) -> None:
    """Insert a `DispatchOutbox` row for the `NodeRun` parked on `agent_run_id`, if any.

    A no-op for the overwhelming majority of approval decisions, which have
    nothing to do with a workflow at all - one indexed lookup on
    `node_runs.waiting_agent_run_id` settles that.
    """
    async with get_worker_db_context() as db:
        found = await workflow_run_repo.find_node_run_waiting_on_agent_run(
            db, agent_run_id, organization_id=organization_id
        )
        if found is None:
            return
        approvals = await agent_run_repo.list_approvals_for_run(
            db, run_id=agent_run_id, organization_id=organization_id
        )
        if any(approval.status == ApprovalStatus.PENDING.value for approval in approvals):
            # This agent run parked on more than one approval, and another
            # decision on it is still outstanding - mirrors
            # `list_stale_approval_waits()`'s own "nothing still pending"
            # gate, and the identical condition `AgentRunnerService.
            # _decisions` requires before it will replay a park. Enqueuing
            # now would dispatch a continuation `_decisions` immediately
            # rejects, and - since only one live outbox row is ever allowed
            # per node run - would leave the decision that actually clears
            # the last pending approval with nothing left to enqueue.
            return
        run = await workflow_run_repo.get_run_by_id_for_update(db, found.workflow_run_id)
        node_run = await workflow_run_repo.get_node_run_by_id_for_update(db, found.id)
        if (
            run is None
            or node_run is None
            or not still_waiting_on(run, node_run, agent_run_id=agent_run_id)
        ):
            return
        try:
            async with db.begin_nested():
                await workflow_run_repo.create_outbox(
                    db,
                    organization_id=run.organization_id,
                    workflow_run_id=run.id,
                    node_run_id=node_run.id,
                )
        except IntegrityError:
            # Already dispatched - `workflow-reconcile`'s own backstop insert
            # raced this one, or two decisions somehow reached here for the
            # same node run. Either way there is nothing left to do.
            logger.info(
                "workflow_approval_wake_already_dispatched", extra={"node_run_id": str(node_run.id)}
            )
