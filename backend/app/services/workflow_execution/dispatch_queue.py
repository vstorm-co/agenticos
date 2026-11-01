"""Queueing a workflow node's dispatch: the outbox row and its job, in one transaction.

`dispatch_outbox` is where a run's position lives; the `workflow-dispatch-node` job
is only what wakes a worker for one row. Both are written on the caller's session,
so they commit or roll back together and the wake-up cannot be lost between the
two - and `NOTIFY` fires only once the row is there to claim. A row due later (a
timer, a retry's backoff) has its job `run_after` the same instant: the job is the
timer.

`workflow-dispatch-poll` and `workflow-reconcile` are the backstop for a job that
died or was lost, not the way work normally starts.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import DispatchOutbox, WorkflowRun, WorkflowRunTrigger
from app.repositories import workflow_run as workflow_run_repo
from app.services.background_jobs import enqueue
from app.worker.jobs import WORKFLOW_DISPATCH_NODE, DispatchWorkflowNode, Priority

# More than any chain of calls the engine admits (`MAX_CALL_DEPTH`), so the walk ends.
_MAX_CALL_HOPS = 32

# A person or a caller is waiting on these (a webhook's Respond step has thirty
# seconds); the rest start themselves and can wait behind them in the workflow pool.
_WAITED_ON = frozenset(
    {
        WorkflowRunTrigger.API,
        WorkflowRunTrigger.WEBSOCKET,
        WorkflowRunTrigger.WEBHOOK,
        WorkflowRunTrigger.CHAT,
        WorkflowRunTrigger.FORM,
        WorkflowRunTrigger.CHANNEL_MESSAGE,
        WorkflowRunTrigger.AGENT,
        WorkflowRunTrigger.APP,
    }
)


async def priority_for(db: AsyncSession, run: WorkflowRun) -> Priority:
    """The queue priority of a run's nodes, from what started it.

    A successor node inherits it: it is derived from the run, not the node. A run
    a `workflow.run` step called takes its caller's, up the chain of calls, since
    whoever waits on the caller waits on it.
    """
    current = run
    for _ in range(_MAX_CALL_HOPS):
        if current.triggered_by != WorkflowRunTrigger.WORKFLOW_CALL or (
            current.causation_run_id is None
        ):
            break
        caller = await workflow_run_repo.get_run(
            db, current.causation_run_id, organization_id=current.organization_id
        )
        if caller is None:
            break
        current = caller
    return Priority.INTERACTIVE if current.triggered_by in _WAITED_ON else Priority.SCHEDULED


async def queue_dispatch(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    node_run_id: UUID,
    available_at: datetime | None = None,
) -> DispatchOutbox:
    """Insert `node_run_id`'s dispatch row and queue the job that runs it.

    `available_at=None` is due now by the database's clock; a later time is a
    timer or a retry's backoff, and the job is not claimable before it. Raises
    `IntegrityError` at the row's flush when one is already live for the node,
    before any job is written, so a caller that treats that as "already
    dispatched" wraps this in `db.begin_nested()`.
    """
    outbox = await workflow_run_repo.create_outbox(
        db,
        organization_id=run.organization_id,
        workflow_run_id=run.id,
        node_run_id=node_run_id,
        available_at=available_at,
    )
    await enqueue(
        db,
        WORKFLOW_DISPATCH_NODE,
        DispatchWorkflowNode(workflow_run_id=run.id, node_run_id=node_run_id),
        organization_id=run.organization_id,
        run_after=available_at,
        priority=await priority_for(db, run),
    )
    return outbox


async def queue_dispatch_job(db: AsyncSession, row: DispatchOutbox) -> None:
    """Queue a job for a row that already exists and is due: the backstop sweeps' path.

    A dedupe key keeps one queued copy per node however often a sweep looks
    while the pool is backed up or the kind is paused. It is never used for a
    direct enqueue: a queued job with a future `run_after` would hold the key
    and drop a due-now job queued behind it.
    """
    run = await workflow_run_repo.get_run(
        db, row.workflow_run_id, organization_id=row.organization_id
    )
    await enqueue(
        db,
        WORKFLOW_DISPATCH_NODE,
        DispatchWorkflowNode(workflow_run_id=row.workflow_run_id, node_run_id=row.node_run_id),
        organization_id=row.organization_id,
        # A run deleted since leaves a job that ends `nothing_to_claim`.
        priority=Priority.SCHEDULED if run is None else await priority_for(db, run),
        dedupe_key=f"workflow-dispatch:{row.node_run_id}",
    )


async def wake_now(db: AsyncSession, *, run: WorkflowRun, node_run_id: UUID) -> None:
    """Bring a node's pending row forward to now and queue a due-now job for it.

    The job the row was first queued with is still waiting for the old time; when
    it comes it finds the row done and ends `nothing_to_claim`. Not deduped, for
    the reason `queue_dispatch_job` gives.
    """
    await workflow_run_repo.bring_forward_outbox(db, node_run_id=node_run_id)
    await enqueue(
        db,
        WORKFLOW_DISPATCH_NODE,
        DispatchWorkflowNode(workflow_run_id=run.id, node_run_id=node_run_id),
        organization_id=run.organization_id,
        priority=await priority_for(db, run),
    )
