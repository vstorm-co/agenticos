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

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from prefect import flow
from prefect.deployments import run_deployment
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_worker_db_context

if TYPE_CHECKING:
    from app.services.workflow_execution.dispatcher import BegunAttempt

logger = logging.getLogger(__name__)

# Both halves - the flow's own name and its registered deployment name - are
# set together in `app/worker/prefect_app.py`; they match by design, the same
# "<flow-name>/<deployment-name>" handle `trigger_tasks._RUN_TRIGGER_DEPLOYMENT`
# addresses its own worker deployment with.
_DISPATCH_NODE_DEPLOYMENT = "workflow-dispatch-node/workflow-dispatch-node"


async def _submit_dispatch(*, workflow_run_id: str, node_run_id: str) -> None:
    """Submit one dispatch tick to the `workflow-dispatch-node` deployment.

    `run_deployment(..., timeout=0)` enqueues the run on the worker pool and
    returns as soon as it is accepted, without waiting for it to finish - the
    same submit-and-return shape `trigger_tasks.dispatch_trigger_fire` uses,
    and for the same reason: a node handler can be a real external call (an
    HTTP request, an agent run), and calling the flow function directly -
    rather than through the deployment - would run it as a local coroutine in
    whatever process happens to reach this line instead, competing with that
    process's own work rather than a worker capped by `PREFECT_RUNNER_LIMIT`.
    """
    # `run_deployment` is sync-compatible: its stub unions the coroutine it
    # returns in an async context with the `FlowRun` a sync caller gets, and ty
    # cannot tell which applies. Awaiting it is correct here.
    await run_deployment(  # ty: ignore[invalid-await]
        name=_DISPATCH_NODE_DEPLOYMENT,
        parameters={"workflow_run_id": workflow_run_id, "node_run_id": node_run_id},
        timeout=0,
    )


def trigger_dispatch(db: AsyncSession, *, workflow_run_id: UUID, node_run_id: UUID) -> None:
    """The low-latency direct trigger, queued for once `db` commits.

    Losing this is not a bug - `workflow-dispatch-poll` finds the same row
    once its submission marker is a lease old - so this is best-effort and
    never awaited by its caller. For a request's session
    (`WorkflowExecutionService.start`); a worker submits what `settle` made
    ready itself, after its own commit, rather than handing it to a task the
    flow's process may not outlive.
    """
    from app.core.background import spawn_after_commit

    spawn_after_commit(
        db,
        _submit_dispatch(workflow_run_id=str(workflow_run_id), node_run_id=str(node_run_id)),
        name="workflow-dispatch-node",
    )


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

    async with _lease_kept_alive(begun):
        outcome = await dispatcher.call_handler(begun)

    async with get_worker_db_context() as db:
        ready = await dispatcher.settle(db, begun=begun, outcome=outcome)
    # After the commit, so each submitted flow can claim the row it names.
    await _submit_each(ready)
    return "settled"


@contextlib.asynccontextmanager
async def _lease_kept_alive(begun: BegunAttempt) -> AsyncIterator[None]:
    """Renew the claim's lease for as long as the handler runs.

    The lease frees a claim whose worker *died*; only the worker can tell
    "died" from "still running", so it renews on an interval well inside the
    lease. Without this a healthy handler that ran past one lease was
    reclaimed mid-call: an idempotent node ran twice, and a non-idempotent
    one was escalated and its real result discarded. The same shape as
    `AgentTriggerService._keep_lease_alive`.
    """
    renewer = asyncio.create_task(_renew_until_lost(begun))
    try:
        yield
    finally:
        renewer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renewer


async def _renew_until_lost(begun: BegunAttempt) -> None:
    from app.services.workflow_execution import dispatcher

    interval = settings.WORKFLOW_DISPATCH_LEASE_SECONDS / 3
    while True:
        await asyncio.sleep(interval)
        try:
            # Its own short transaction, so the new expiry commits and the
            # reconciler's sessions see it.
            async with get_worker_db_context() as db:
                held = await dispatcher.renew_lease(db, begun=begun)
        except Exception:
            # One failed renewal is not a lost claim: the next tick tries
            # again, and if every one fails the lease simply runs out and the
            # fence in `settle` decides. Raising here would surface at the end
            # of the handler call instead and discard its result.
            logger.exception(
                "workflow_dispatch_lease_renewal_failed",
                extra={"node_run_id": str(begun.node_run_id)},
            )
            continue
        if not held:
            begun.dispatch_context.claim.lost = True
            logger.warning(
                "workflow_dispatch_claim_lost", extra={"node_run_id": str(begun.node_run_id)}
            )
            return


async def _submit_each(pairs: list[tuple[UUID, UUID]]) -> int:
    """Submit a dispatch tick for each pair; returns how many were accepted.

    Each submission is isolated, as in `trigger_tasks.check_agent_triggers_flow`:
    one Prefect API error must not cost the rest of the batch its submission.
    A failed one is not un-stamped - `run_deployment` can enqueue the run and
    then lose the response, so the row waits out its submission interval and
    the poll or the stale-claim sweep submits it again after that.
    """
    submitted = 0
    for workflow_run_id, node_run_id in pairs:
        try:
            await _submit_dispatch(
                workflow_run_id=str(workflow_run_id), node_run_id=str(node_run_id)
            )
        except Exception:
            logger.exception(
                "workflow_dispatch_submit_failed", extra={"node_run_id": str(node_run_id)}
            )
        else:
            submitted += 1
    return submitted


def _resubmit_before() -> datetime:
    """Rows submitted after this are left alone: a lease is how long a queued
    flow run gets to claim its row before it is assumed lost."""
    return datetime.now(UTC) - timedelta(seconds=settings.WORKFLOW_DISPATCH_LEASE_SECONDS)


@flow(name="workflow-dispatch-poll", log_prints=True)
async def workflow_dispatch_poll_flow() -> int:
    """Find `pending` outbox rows due now and trigger a dispatch tick for each.

    The guarantee of forward progress this design calls for: the direct
    submissions on start and on every advance can be lost (the process dies
    before they run) - this is what notices regardless, on a short interval,
    and it costs one query when there is nothing to do. A row already
    submitted within the last lease is skipped rather than submitted again on
    every tick, so a backed-up worker pool is not buried in duplicate flow
    runs.

    Each pending row is submitted to the worker deployment independently
    (`_submit_dispatch`, not the flow function called directly) so one row
    whose handler hangs cannot hold up claiming the rest of this batch.
    """
    from app.repositories import workflow_run as workflow_run_repo

    async with get_worker_db_context() as db:
        rows = await workflow_run_repo.take_due_for_submission(
            db, resubmit_before=_resubmit_before()
        )
        pairs = [(row.workflow_run_id, row.node_run_id) for row in rows]

    submitted = await _submit_each(pairs)
    if pairs:
        logger.info("workflow_dispatch_poll: submitted %d of %d row(s)", submitted, len(pairs))
    return submitted


@flow(name="workflow-reconcile", log_prints=True)
async def workflow_reconcile_flow() -> dict[str, int]:
    """The slower sweep: reclaim stale claims, resolve orphaned attempts, wake
    stale approval decisions. Structurally `stale_run_sweep_flow` applied to
    three shapes of stranded workflow-execution row - see
    `app.services.workflow_execution.reconciler` for what each one is.
    """
    from app.services.workflow_execution.reconciler import WorkflowReconcilerService

    # One transaction per sweep: each commits on its own, so a sweep that
    # aborts (a deadlock Postgres broke, say) takes only its own work with it.
    async with get_worker_db_context() as db:
        stale_pairs = await WorkflowReconcilerService(db).stale_claims()
    async with get_worker_db_context() as db:
        resolved = await WorkflowReconcilerService(db).resolve_orphaned_attempts()
    async with get_worker_db_context() as db:
        woken = await WorkflowReconcilerService(db).wake_stale_approval_decisions()

    result = {
        "reclaimed_claims": await _submit_each(stale_pairs),
        "resolved_attempts": resolved,
        "woken_approvals": woken,
    }
    if any(result.values()):
        logger.warning("workflow_reconcile: %s", result)
    return result
