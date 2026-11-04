"""Workflow durable execution - one job per dispatch tick, plus its sweeps.

`workflow-dispatch-node` is deliberately not a job per `WorkflowRun`: holding a
run's position in one job's call stack for its whole life - through
`waiting_approval`, hours or days - is the wrong shape. Postgres stays the only
source of truth for run position (`dispatch_outbox`); a job is only what wakes a
worker for one outbox row, queued with the row in one transaction
(`app.services.workflow_execution.dispatch_queue`). The sweeps are the backstop
for a job that died or was lost.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.config import settings
from app.db.session import get_worker_db_context
from app.services.workflow_execution.context import ClaimState
from app.worker.jobs import DispatchOutcome, DispatchWorkflowNode

logger = logging.getLogger(__name__)


async def dispatch_node(job: DispatchWorkflowNode) -> DispatchOutcome:
    """One node attempt, start to finish: claim, run, settle.

    Answers a status word rather than raising on the ordinary "nothing to do"
    outcomes (lost the claim race, the run ended underneath it, a duplicate job
    for a row already done): a job that answers `nothing_to_claim` is not a
    failure to retry or alert on. What `settle` made ready has its jobs queued
    in settle's own transaction.
    """
    from app.services.workflow_execution import dispatcher

    run_id = job.workflow_run_id
    node_id = job.node_run_id

    async with get_worker_db_context() as db:
        outbox = await dispatcher.claim(db, node_run_id=node_id)
    if outbox is None:
        return DispatchOutcome(status="nothing_to_claim")
    # `claim`'s CAS `UPDATE ... SET claimed_by = :token ... RETURNING` always
    # sets it on the row it returns - `claimed_by` is nullable only for a
    # `pending` row nobody has claimed yet, which this is not.
    assert outbox.claimed_by is not None

    token = outbox.claimed_by
    claim = ClaimState()
    # From the claim to the settle's commit: a lease that runs out while
    # `begin_attempt` resolves the call, or while `settle` waits for its lock,
    # has a healthy attempt reclaimed just as surely as one that runs out
    # mid-handler.
    async with _lease_kept_alive(node_id, token, claim):
        async with get_worker_db_context() as db:
            begun = await dispatcher.begin_attempt(
                db, workflow_run_id=run_id, node_run_id=node_id, token=token, claim=claim
            )
        if begun is None:
            return DispatchOutcome(status="not_dispatched")
        outcome = await dispatcher.call_handler(begun)
        async with get_worker_db_context() as db:
            await dispatcher.settle(db, begun=begun, outcome=outcome)
    return DispatchOutcome(status="settled")


@contextlib.asynccontextmanager
async def _lease_kept_alive(
    node_run_id: UUID, token: UUID, claim: ClaimState
) -> AsyncGenerator[None]:
    """Renew the claim's lease for as long as the block runs.

    The lease frees a claim whose worker *died*; only the worker can tell
    "died" from "still running", so it renews on an interval well inside the
    lease. Without this a healthy attempt that ran past one lease was
    reclaimed mid-call: an idempotent node ran twice, and a non-idempotent
    one was escalated and its real result discarded. The same shape as
    `AgentTriggerService._keep_lease_alive`. This is the outbox row's lease,
    independent of the job's own, which the worker's heartbeat keeps.
    """
    renewer = asyncio.create_task(_renew_until_lost(node_run_id, token, claim))
    try:
        yield
    finally:
        renewer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renewer


async def _renew_until_lost(node_run_id: UUID, token: UUID, claim: ClaimState) -> None:
    from app.services.workflow_execution import dispatcher

    interval = settings.WORKFLOW_DISPATCH_LEASE_SECONDS / 3
    while True:
        await asyncio.sleep(interval)
        try:
            # Its own short transaction, so the new expiry commits and the
            # reconciler's sessions see it.
            async with get_worker_db_context() as db:
                held = await dispatcher.renew_lease(db, node_run_id=node_run_id, token=token)
        except Exception:
            # One failed renewal is not a lost claim: the next tick tries
            # again, and if every one fails the lease simply runs out and the
            # fence in `settle` decides. Raising here would surface at the end
            # of the block instead and discard the attempt's result.
            logger.exception(
                "workflow_dispatch_lease_renewal_failed", extra={"node_run_id": str(node_run_id)}
            )
            continue
        if not held:
            claim.lost = True
            logger.warning("workflow_dispatch_claim_lost", extra={"node_run_id": str(node_run_id)})
            return


def _resubmit_before() -> datetime:
    """Rows whose job came due after this are left alone: a lease is how long a
    queued job gets to claim its row before it is assumed lost."""
    return datetime.now(UTC) - timedelta(seconds=settings.WORKFLOW_DISPATCH_LEASE_SECONDS)


async def poll_due_dispatches() -> int:
    """Queue a job for each `pending` outbox row due now whose own job did not come.

    The backstop for forward progress: every row has a job queued with it, so
    this notices only a job that died or was lost to a restore,
    and costs one query when there is nothing to do. A row whose job came due
    within the last lease is skipped, and the jobs are deduped per node, so a
    backed-up pool or a paused kind is not buried in copies.

    The rows are stamped and their jobs queued in one transaction, so a stamp
    never outlives the job it stands for.
    """
    from app.repositories import workflow_run as workflow_run_repo
    from app.services.workflow_execution import dispatch_queue

    async with get_worker_db_context() as db:
        rows = await workflow_run_repo.take_due_for_submission(
            db, resubmit_before=_resubmit_before()
        )
        for row in rows:
            await dispatch_queue.queue_dispatch_job(db, row)
    if rows:
        logger.info("workflow_dispatch_poll: queued %d row(s)", len(rows))
    return len(rows)


async def reconcile() -> dict[str, int]:
    """The slower sweep: reclaim stale claims, resolve orphaned attempts, wake
    stale approval decisions and `human.approval` steps. Structurally
    `reap_stale_runs` applied to four shapes of stranded workflow-execution row - see
    `app.services.workflow_execution.reconciler` for what each one is.
    """
    from app.services.workflow_execution.reconciler import WorkflowReconcilerService

    # One transaction per sweep: each commits on its own, so a sweep that
    # aborts (a deadlock Postgres broke, say) takes only its own work with it.
    async with get_worker_db_context() as db:
        reclaimed = await WorkflowReconcilerService(db).stale_claims()
    async with get_worker_db_context() as db:
        resolved = await WorkflowReconcilerService(db).resolve_orphaned_attempts()
    async with get_worker_db_context() as db:
        woken = await WorkflowReconcilerService(db).wake_stale_approval_decisions()
    async with get_worker_db_context() as db:
        woken_steps = await WorkflowReconcilerService(db).wake_stale_step_approvals()

    result = {
        "reclaimed_claims": reclaimed,
        "resolved_attempts": resolved,
        "woken_approvals": woken,
        "woken_step_approvals": woken_steps,
    }
    if any(result.values()):
        logger.warning("workflow_reconcile: %s", result)
    return result


async def check_workflow_schedules() -> int:
    """Heartbeat: fire every workflow schedule due now (#1792).

    The claim, the clock advance, each admitted run and its first dispatch job
    commit in one transaction, so a tick either happened or did not: a worker
    that dies before the commit leaves the clock where it was and the next tick
    fires the same instant.
    """
    from app.services.workflow_exposure import WorkflowExposureService

    async with get_worker_db_context() as db:
        admitted = await WorkflowExposureService(db).fire_due(now=datetime.now(UTC))
    if admitted:
        logger.info("workflow_schedules_check: fired %d schedule(s)", len(admitted))
    return len(admitted)


async def consume_table_triggers() -> int:
    """Heartbeat: judge every added record against its table's triggers (#1785).

    Each claimed event's admissions, their first dispatch jobs and its delivered
    stamp commit together, so an event is judged in full or not at all.
    """
    from app.services.virtual_tables.triggers import TableTriggerConsumer

    async with get_worker_db_context() as db:
        admitted = await TableTriggerConsumer(db).consume()
    if admitted:
        logger.info("workflow_table_triggers: admitted %d run(s)", len(admitted))
    return len(admitted)


async def check_workflow_log_alerts() -> int:
    """Heartbeat: judge every enabled log alert rule not holding off from its last alert, each
    in a transaction of its own.

    A rule that cannot be judged - a notification write failed, say - is logged and left for the next tick; it never stops
    the rules after it, and its own rows roll back with it.
    """
    from app.services.workflow_log_alerts import WorkflowLogAlertService

    async with get_worker_db_context() as db:
        rule_ids = await WorkflowLogAlertService(db).due_rule_ids(now=datetime.now(UTC))
    fired = 0
    for rule_id in rule_ids:
        try:
            async with get_worker_db_context() as db:
                if await WorkflowLogAlertService(db).evaluate(rule_id, now=datetime.now(UTC)):
                    fired += 1
        except Exception:
            logger.exception("workflow_log_alert_failed", extra={"rule_id": str(rule_id)})
    if fired:
        logger.info("workflow_log_alerts: fired %d rule(s)", fired)
    return fired


# Runs removed per transaction, and transactions per sweep: a workflow whose
# retention was just shortened clears over a few days rather than in one hold.
RETENTION_BATCH = 200
RETENTION_BATCHES = 50


async def sweep_workflow_run_retention() -> int:
    """Daily: remove the runs their workflow's settings no longer keep (#1944).

    Each batch's rows go in one committed transaction; only then are the bytes
    of the files those runs made unlinked, so a rollback never leaves a row
    naming a file already gone. An unlink that fails is logged, not retried: the
    row is gone and the warning is the one trace of the path.
    """
    from app.repositories import workflow_run as workflow_run_repo
    from app.services.file_storage import delete_files_best_effort

    removed = 0
    for _ in range(RETENTION_BATCHES):
        async with get_worker_db_context() as db:
            taken = await workflow_run_repo.take_expired_runs(
                db, now=datetime.now(UTC), limit=RETENTION_BATCH
            )
        if not taken:
            break
        await delete_files_best_effort([path for _run_id, paths in taken for path in paths])
        removed += len(taken)
    if removed:
        logger.info("workflow_run_retention_sweep: removed %d run(s)", removed)
    return removed
