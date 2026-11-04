"""Closing the work a workflow run still has under way when it ends or a step is stopped.

A run that ends - cancelled, failed, over budget - or a loop that stops an iteration
leaves live steps behind: ones queued, ones waiting out a backoff or a timer, ones
parked on a person's decision or on an agent run. This module is the one place that
closes all of it, so that every way a run ends does the same:

- the step's dispatch row and its queued `workflow-dispatch-node` job are withdrawn,
  so nothing starts it;
- a pending `human.approval` request is closed, so nobody decides it for nothing;
- the agent run a step parked on is stopped (`AgentRunnerService.stop_parked_for_workflow`);
- the step moves to `cancelled`, with a `node.cancelled` event.

An attempt already executing is not interrupted: it settles on its own, and
`dispatcher.settle` records what it did without advancing the run. A step that parks
after the run ended is closed by `withdraw_late_wait`.

Lock order: every caller already holds the organization's advisory locks and the run's
row. The agent run's row is locked after them, and no path locks an agent run and then
waits for a workflow run - an approval decision wakes the workflow run after its commit.
Several parked agent runs are claimed in id order and audited only after the last claim.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import NodeRun, NodeRunStatus, WorkflowRun
from app.repositories import background_job as background_job_repo
from app.repositories import workflow_approval as workflow_approval_repo
from app.repositories import workflow_run as workflow_run_repo
from app.services.workflow_execution import events
from app.worker.jobs import WORKFLOW_DISPATCH_NODE

if TYPE_CHECKING:
    from app.services.agent_runner import ParkedStop


async def _stop_agent_runs(
    db: AsyncSession, *, organization_id: UUID, agent_run_ids: Sequence[UUID | None]
) -> list[ParkedStop]:
    """Stop the parked agent runs, row work only: the caller audits them last."""
    ids = [agent_run_id for agent_run_id in agent_run_ids if agent_run_id is not None]
    if not ids:
        return []
    # Imported here: the runner imports `workflow_execution` lazily the other way round.
    from app.services.agent_runner import AgentRunnerService

    return await AgentRunnerService(db).stop_parked_for_workflow(
        ids, organization_id=organization_id
    )


async def _audit_stops(db: AsyncSession, stops: Sequence[ParkedStop]) -> None:
    from app.services.agent_runner import AgentRunnerService

    await AgentRunnerService(db).record_parked_stops(stops)


async def _cancel_nodes(
    db: AsyncSession, *, run: WorkflowRun, node_runs: Sequence[NodeRun], now: datetime
) -> None:
    """Stop the agent run each step parks on, then move the steps to `cancelled`.

    Every row is locked and written first and the audit entries come last: the audit
    chain lock must follow every row lock (`app.core.audit.record_audit`), and
    stopping the runs one by one, audit and all, would take it between two claims.
    """
    stops = await _stop_agent_runs(
        db,
        organization_id=run.organization_id,
        agent_run_ids=[node_run.waiting_agent_run_id for node_run in node_runs],
    )
    for node_run in node_runs:
        await workflow_run_repo.update_node_run(
            db,
            node_run=node_run,
            update_data={
                "status": NodeRunStatus.CANCELLED.value,
                "ended_at": now,
                "waiting_reason": None,
                "waiting_agent_run_id": None,
            },
        )
        await events.append(
            db, run=run, kind=events.EventKind.NODE_CANCELLED, node_run_id=node_run.id
        )
    await _audit_stops(db, stops)


async def stop_node_work(
    db: AsyncSession, *, run: WorkflowRun, node_runs: Sequence[NodeRun], now: datetime
) -> None:
    """Close what these steps have under way and move them to `cancelled`.

    The run itself is untouched: a loop stopping one iteration uses this and the run
    goes on.
    """
    if not node_runs:
        return
    ids = [node_run.id for node_run in node_runs]
    await workflow_run_repo.cancel_live_outbox_for_node_runs(db, node_run_ids=ids)
    for node_run_id in ids:
        await background_job_repo.cancel_queued_for_payload(
            db,
            kind=WORKFLOW_DISPATCH_NODE.kind,
            organization_id=run.organization_id,
            payload_key="node_run_id",
            payload_value=node_run_id,
        )
    await workflow_approval_repo.cancel_pending_for_node_runs(db, ids)
    await _cancel_nodes(db, run=run, node_runs=node_runs, now=now)


async def stop_run_work(db: AsyncSession, *, run: WorkflowRun, now: datetime) -> list[NodeRun]:
    """Close everything `run` has under way, and return the steps it ended.

    The caller writes the run's terminal status and its event, and delivers its result.
    A loop mid-iteration has no dispatch row of its own - its row stays `running` until
    its last iteration ends - so it is ended here with every other live step.
    """
    await workflow_run_repo.cancel_live_outbox_for_run(db, workflow_run_id=run.id)
    # The jobs of a wait or a backoff: left queued they would sit in the
    # background-jobs panel until due, to find nothing to do.
    await background_job_repo.cancel_queued_for_payload(
        db,
        kind=WORKFLOW_DISPATCH_NODE.kind,
        organization_id=run.organization_id,
        payload_key="workflow_run_id",
        payload_value=run.id,
    )
    await workflow_approval_repo.cancel_pending_for_run(db, run.id)
    live = await workflow_run_repo.list_live_node_runs(db, workflow_run_id=run.id)
    await _cancel_nodes(db, run=run, node_runs=live, now=now)
    return live


async def withdraw_late_wait(
    db: AsyncSession, *, run: WorkflowRun, node_run: NodeRun, waiting_agent_run_id: UUID | None
) -> None:
    """Close the wait of a step that parked after it was stopped or its run had ended.

    The step's handler asked a person or started an agent run before the stop reached
    it, so both exist and nothing will ever answer them. Only this step's request is
    closed: the run may still be live, with other branches waiting for people.
    """
    await workflow_approval_repo.cancel_pending_for_node_runs(db, [node_run.id])
    stops = await _stop_agent_runs(
        db, organization_id=run.organization_id, agent_run_ids=[waiting_agent_run_id]
    )
    await _audit_stops(db, stops)
