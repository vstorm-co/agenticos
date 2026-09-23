"""Workflow durable execution - one flow per dispatch tick, plus its sweeps.

`workflow-dispatch-node` is deliberately not a flow per `WorkflowRun`: see
`docs/plans/1788-durable-execution.md`'s "Prefect: a flow per dispatch tick"
section for why holding a run's position in one flow's call stack for its
whole life - through `waiting_approval`, hours or days - is the wrong shape.
Postgres stays the only source of truth for run position; Prefect is reduced
to scheduling, backoff and worker fan-out per unit of work, the same as
`ingest_document_flow`.
"""

from __future__ import annotations

import logging
from uuid import UUID

from prefect import flow

from app.db.session import get_worker_db_context

logger = logging.getLogger(__name__)


@flow(name="workflow-dispatch-node")
async def workflow_dispatch_node_flow(workflow_run_id: str, node_run_id: str) -> str:
    """One node attempt, start to finish: claim, run, settle.

    Args are strings - Prefect flow arguments must be serializable, never an
    ORM object or an open session.

    Returns a short status word rather than raising on the ordinary "nothing
    to do" outcomes (lost the claim race, the run ended underneath it): a
    flow run that answers "nothing_to_claim" is not a failure Prefect should
    retry or alert on.
    """
    from app.services.workflow_execution import dispatcher

    run_id = UUID(workflow_run_id)
    node_id = UUID(node_run_id)

    async with get_worker_db_context() as db:
        outbox = await dispatcher.claim(db, node_run_id=node_id)
    if outbox is None:
        return "nothing_to_claim"
    # `claim`'s CAS `UPDATE ... SET claimed_by = :token ... RETURNING` always
    # sets it on the row it returns - `claimed_by` is nullable only for a
    # `pending` row nobody has claimed yet, which this is not.
    assert outbox.claimed_by is not None

    async with get_worker_db_context() as db:
        begun = await dispatcher.begin_attempt(
            db, workflow_run_id=run_id, node_run_id=node_id, token=outbox.claimed_by
        )
    if begun is None:
        return "not_dispatched"

    result, waiting_agent_run_id = await dispatcher.call_handler(begun)

    async with get_worker_db_context() as db:
        await dispatcher.settle(
            db, begun=begun, result=result, waiting_agent_run_id=waiting_agent_run_id
        )
    return "settled"


@flow(name="workflow-dispatch-poll", log_prints=True)
async def workflow_dispatch_poll_flow() -> int:
    """Find `pending` outbox rows due now and trigger a dispatch tick for each.

    The guarantee of forward progress this design calls for: the direct
    trigger `WorkflowExecutionService._trigger_dispatch` fires on start and
    on every advance, but that trigger can be lost (the process dies before
    the spawned task starts) - this is what notices regardless, on a short
    interval, and it costs one query when there is nothing to do.
    """
    from app.repositories import workflow_run as workflow_run_repo

    async with get_worker_db_context() as db:
        rows = await workflow_run_repo.list_pending_outbox(db)
        pairs = [(row.workflow_run_id, row.node_run_id) for row in rows]

    for workflow_run_id, node_run_id in pairs:
        await workflow_dispatch_node_flow(
            workflow_run_id=str(workflow_run_id), node_run_id=str(node_run_id)
        )
    if pairs:
        logger.info("workflow_dispatch_poll: dispatched %d row(s)", len(pairs))
    return len(pairs)


@flow(name="workflow-reconcile", log_prints=True)
async def workflow_reconcile_flow() -> dict[str, int]:
    """The slower sweep: reclaim stale claims, resolve orphaned attempts, wake
    stale approval decisions. Structurally `stale_run_sweep_flow` applied to
    three shapes of stranded workflow-execution row - see
    `app.services.workflow_execution.reconciler` for what each one is.
    """
    from app.services.workflow_execution.reconciler import WorkflowReconcilerService

    async with get_worker_db_context() as db:
        service = WorkflowReconcilerService(db)
        stale_pairs = await service.stale_claims()
        resolved = await service.resolve_orphaned_attempts()
        woken = await service.wake_stale_approval_decisions()

    for workflow_run_id, node_run_id in stale_pairs:
        await workflow_dispatch_node_flow(
            workflow_run_id=str(workflow_run_id), node_run_id=str(node_run_id)
        )

    result = {
        "reclaimed_claims": len(stale_pairs),
        "resolved_attempts": resolved,
        "woken_approvals": woken,
    }
    if any(result.values()):
        logger.warning("workflow_reconcile: %s", result)
    return result
