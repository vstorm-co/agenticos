"""Workflow run repository (PostgreSQL async).

Pure data access for the six durable-execution tables. Concurrency-sensitive
writes - claiming an outbox row, inserting one under the live-dispatch unique
index - are plain conditional `UPDATE`/`INSERT` statements here; the compare
and the fallback for a lost race belong to the caller
(`app.services.workflow_execution`), the same split `agent_run_repo.decide_approval`
and its caller already use.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, func, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeAttempt,
    NodeAttemptStatus,
    NodeRun,
    NodeRunStatus,
    ResourceRef,
    WaitingReason,
    WorkflowEvent,
    WorkflowRun,
    WorkflowRunStatus,
)

# WorkflowRun


async def create_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
    workflow_version_id: UUID | None,
    draft_graph_snapshot: dict[str, Any] | None,
    mode: str,
    triggered_by: str,
    execution_principal_user_id: UUID | None,
    budget_limit: Decimal | None,
    deadline_at: datetime | None,
    root_run_id: UUID | None,
    causation_run_id: UUID | None,
    visited_trigger_ids: list[str],
    depth: int,
    started_at: datetime,
) -> WorkflowRun:
    # `root_run_id` is NOT NULL, so it must be known before the first
    # `INSERT` - not filled in after a flush "mints" the id, which never gets
    # that far: the first flush is the INSERT, and it fails the NOT NULL
    # constraint before anything is assigned. Generating the id here, rather
    # than leaving it to the column's own `default=uuid.uuid4`, is what makes
    # it known up front: a root run points at itself.
    run_id = uuid4()
    run = WorkflowRun(
        id=run_id,
        organization_id=organization_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        draft_graph_snapshot=draft_graph_snapshot,
        mode=mode,
        triggered_by=triggered_by,
        execution_principal_user_id=execution_principal_user_id,
        budget_limit=budget_limit,
        deadline_at=deadline_at,
        root_run_id=root_run_id or run_id,
        causation_run_id=causation_run_id,
        visited_trigger_ids=visited_trigger_ids,
        depth=depth,
        started_at=started_at,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def get_run(db: AsyncSession, run_id: UUID, *, organization_id: UUID) -> WorkflowRun | None:
    result = await db.execute(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id, WorkflowRun.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def get_run_for_update(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID
) -> WorkflowRun | None:
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.id == run_id, WorkflowRun.organization_id == organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_run_by_id_for_update(db: AsyncSession, run_id: UUID) -> WorkflowRun | None:
    """Unscoped, row-locked - for the dispatcher and reconciler, which act on
    ids a trusted internal caller supplies (a Prefect flow argument, a sweep's
    own scan), never on a caller-supplied id an organization boundary must
    still be checked against. Every write this makes is still stamped with
    the row's own `organization_id`.

    Every locking read here also sets `populate_existing`: a row this session
    already loaded (a sweep's own scan) would otherwise come back with the
    attributes it had *before* the lock was granted, and a check made on
    those after waiting for the lock would be a check of stale values."""
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def list_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID | None = None,
    visible_workflow_ids: list[UUID] | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[WorkflowRun], int]:
    """Runs in `organization_id`, optionally narrowed to one workflow.

    `visible_workflow_ids` is consulted only when `workflow_id` is not given
    - `None` means the caller's role already reaches every workflow (the
    same contract `app.services.access.visible_resource_ids` documents), and
    an empty list is a caller with no visible workflow at all, not "no
    filter" - so it must narrow the query to nothing, never be treated the
    same as `None`.
    """
    where = [WorkflowRun.organization_id == organization_id]
    if workflow_id is not None:
        where.append(WorkflowRun.workflow_id == workflow_id)
    elif visible_workflow_ids is not None:
        where.append(WorkflowRun.workflow_id.in_(visible_workflow_ids))
    total = await db.scalar(select(func.count()).select_from(WorkflowRun).where(*where)) or 0
    result = await db.execute(
        select(WorkflowRun)
        .where(*where)
        .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def update_run(
    db: AsyncSession, *, run: WorkflowRun, update_data: dict[str, Any]
) -> WorkflowRun:
    for field, value in update_data.items():
        setattr(run, field, value)
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


# NodeRun


async def create_node_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_run_id: UUID,
    node_instance_id: UUID,
    scope_path: list[dict[str, Any]],
) -> NodeRun:
    node_run = NodeRun(
        organization_id=organization_id,
        workflow_run_id=workflow_run_id,
        node_instance_id=node_instance_id,
        scope_path=scope_path,
    )
    db.add(node_run)
    await db.flush()
    await db.refresh(node_run)
    return node_run


async def get_node_run(
    db: AsyncSession, node_run_id: UUID, *, organization_id: UUID
) -> NodeRun | None:
    result = await db.execute(
        select(NodeRun).where(NodeRun.id == node_run_id, NodeRun.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def get_node_run_for_update(
    db: AsyncSession, node_run_id: UUID, *, organization_id: UUID
) -> NodeRun | None:
    result = await db.execute(
        select(NodeRun)
        .where(NodeRun.id == node_run_id, NodeRun.organization_id == organization_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def get_node_run_by_id(db: AsyncSession, node_run_id: UUID) -> NodeRun | None:
    """Unscoped - see `get_run_by_id_for_update` for why the dispatcher needs this."""
    result = await db.execute(select(NodeRun).where(NodeRun.id == node_run_id))
    return result.scalar_one_or_none()


async def get_node_run_by_id_for_update(db: AsyncSession, node_run_id: UUID) -> NodeRun | None:
    result = await db.execute(
        select(NodeRun)
        .where(NodeRun.id == node_run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_node_run_by_identity(
    db: AsyncSession,
    *,
    workflow_run_id: UUID,
    node_instance_id: UUID,
    scope_path: list[dict[str, Any]],
) -> NodeRun | None:
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.workflow_run_id == workflow_run_id,
            NodeRun.node_instance_id == node_instance_id,
            NodeRun.scope_path == scope_path,
        )
    )
    return result.scalar_one_or_none()


async def list_node_runs(db: AsyncSession, *, workflow_run_id: UUID) -> list[NodeRun]:
    result = await db.execute(
        select(NodeRun)
        .where(NodeRun.workflow_run_id == workflow_run_id)
        .order_by(NodeRun.created_at)
    )
    return list(result.scalars().all())


async def find_node_run_waiting_on_agent_run(
    db: AsyncSession, agent_run_id: UUID, *, organization_id: UUID
) -> NodeRun | None:
    """The `NodeRun` parked on this agent run, if any - the approval wake-up needs it."""
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.waiting_agent_run_id == agent_run_id,
            NodeRun.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_stale_approval_waits(db: AsyncSession, *, limit: int = 100) -> list[NodeRun]:
    """`NodeRun`s parked on an approval every blocking decision has already answered.

    The reconciler's backstop for the direct wake `ApprovalService.decide`
    queues via `spawn_after_commit`: if that trigger is lost, this finds the
    same shape from the data alone.

    "Already answered" is read off `tool_approvals` directly - no row still
    `pending` for the parked `agent_runs` id - rather than off
    `agent_runs.status`: `ApprovalService.decide` only ever writes the
    `ToolApproval` row (`agent_runs.paused_state`/`status` stay exactly as
    `AgentRunnerService.resume` itself changes them, per this design's own
    "recorded exactly where it is today"), so `agent_runs.status` never
    actually leaves `awaiting_approval` until *something* calls `resume` -
    which is precisely the trigger this function exists to substitute for
    when it is lost. `AgentRunnerService._decisions` requires the identical
    "nothing still pending" condition before it will replay a park, so this
    mirrors the one check that already decides whether a resume can proceed.
    `agent_runs.status == awaiting_approval` is kept as a second guard so an
    agent run cancelled or otherwise moved on by another path is not
    redispatched. A *workflow* run cancelled out from under this wait is a
    third, separate case - `cancel()` leaves a waiting `NodeRun` and its
    linked `agent_runs` row exactly as they were (documented gap:
    `WorkflowExecutionService.cancel`), so the two checks above stay true
    forever and this would otherwise re-insert an outbox row on every sweep,
    for `begin_attempt` to immediately close again as soon as it sees the
    terminal run - forever, not once. Excluding a terminal owning
    `WorkflowRun` here is what stops that.
    """
    live_outbox = (
        select(DispatchOutbox.node_run_id)
        .where(
            DispatchOutbox.status.in_(
                [DispatchOutboxStatus.PENDING.value, DispatchOutboxStatus.CLAIMED.value]
            )
        )
        .distinct()
    )
    still_pending = (
        select(ToolApproval.id)
        .where(
            ToolApproval.run_id == AgentRun.id,
            ToolApproval.status == ApprovalStatus.PENDING.value,
        )
        .exists()
    )
    terminal_statuses = [status.value for status in WorkflowRunStatus if status.is_terminal]
    result = await db.execute(
        select(NodeRun)
        .join(AgentRun, AgentRun.id == NodeRun.waiting_agent_run_id)
        .join(WorkflowRun, WorkflowRun.id == NodeRun.workflow_run_id)
        .where(
            NodeRun.status == NodeRunStatus.WAITING.value,
            NodeRun.waiting_reason == WaitingReason.APPROVAL.value,
            NodeRun.waiting_agent_run_id.is_not(None),
            AgentRun.status == RunStatus.AWAITING_APPROVAL.value,
            WorkflowRun.status.not_in(terminal_statuses),
            ~still_pending,
            NodeRun.id.not_in(live_outbox),
        )
        # By run id, for the same lock-order reason as `list_orphaned_in_flight`.
        .order_by(NodeRun.workflow_run_id, NodeRun.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_node_run(
    db: AsyncSession, *, node_run: NodeRun, update_data: dict[str, Any]
) -> NodeRun:
    for field, value in update_data.items():
        setattr(node_run, field, value)
    db.add(node_run)
    await db.flush()
    await db.refresh(node_run)
    return node_run


# NodeAttempt


async def create_attempt(
    db: AsyncSession,
    *,
    organization_id: UUID,
    node_run_id: UUID,
    attempt_no: int,
    idempotency_key: str,
    retry_guarantee: str | None,
    started_at: datetime,
) -> NodeAttempt:
    attempt = NodeAttempt(
        organization_id=organization_id,
        node_run_id=node_run_id,
        attempt_no=attempt_no,
        idempotency_key=idempotency_key,
        retry_guarantee=retry_guarantee,
        status=NodeAttemptStatus.IN_FLIGHT.value,
        started_at=started_at,
    )
    db.add(attempt)
    await db.flush()
    await db.refresh(attempt)
    return attempt


async def get_attempt(db: AsyncSession, attempt_id: UUID) -> NodeAttempt | None:
    """Always re-read from the database: callers read it under the owning run's
    lock to decide whether the attempt is still `in_flight`."""
    result = await db.execute(
        select(NodeAttempt)
        .where(NodeAttempt.id == attempt_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_latest_attempt(db: AsyncSession, *, node_run_id: UUID) -> NodeAttempt | None:
    result = await db.execute(
        select(NodeAttempt)
        .where(NodeAttempt.node_run_id == node_run_id)
        .order_by(NodeAttempt.attempt_no.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_attempts(db: AsyncSession, *, node_run_id: UUID) -> list[NodeAttempt]:
    result = await db.execute(
        select(NodeAttempt)
        .where(NodeAttempt.node_run_id == node_run_id)
        .order_by(NodeAttempt.attempt_no)
    )
    return list(result.scalars().all())


async def settle_attempt(
    db: AsyncSession,
    *,
    attempt: NodeAttempt,
    status: str,
    result: dict[str, Any] | None,
    cost: Decimal,
    cost_is_partial: bool,
    ended_at: datetime,
) -> NodeAttempt:
    attempt.status = status
    attempt.result = result
    attempt.cost = cost
    attempt.cost_is_partial = cost_is_partial
    attempt.ended_at = ended_at
    db.add(attempt)
    await db.flush()
    await db.refresh(attempt)
    return attempt


async def list_orphaned_in_flight(
    db: AsyncSession, *, before: datetime, limit: int = 100
) -> list[NodeAttempt]:
    """`in_flight` attempts whose owning outbox lease has expired.

    The reconciler's starting point: an attempt committed `in_flight` before
    its handler ran (see `app.services.workflow_execution.dispatcher`), whose
    process died before settling it. Joined through `DispatchOutbox` rather
    than through the attempt's own `started_at`, because the lease - not the
    attempt's age - is what says nobody is still working it.

    Ordered by the owning run's id: the sweep locks each run in turn and holds
    every lock until it commits, so any two sweeps must take them in the same
    order or they can deadlock each other.
    """
    result = await db.execute(
        select(NodeAttempt)
        .join(DispatchOutbox, DispatchOutbox.node_run_id == NodeAttempt.node_run_id)
        .join(NodeRun, NodeRun.id == NodeAttempt.node_run_id)
        .where(
            NodeAttempt.status == NodeAttemptStatus.IN_FLIGHT.value,
            DispatchOutbox.status == DispatchOutboxStatus.CLAIMED.value,
            DispatchOutbox.lease_expires_at.is_not(None),
            DispatchOutbox.lease_expires_at < before,
        )
        .order_by(NodeRun.workflow_run_id, NodeAttempt.id)
        .limit(limit)
    )
    return list(result.scalars().all())


# DispatchOutbox


async def create_outbox(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_run_id: UUID,
    node_run_id: UUID,
    available_at: datetime | None = None,
    submitted: bool = False,
) -> DispatchOutbox:
    """Insert a dispatch row. Raises `IntegrityError` if one is already live.

    Callers that must treat a live row as "already dispatched" rather than a
    failure wrap this in `db.begin_nested()`, the same savepoint shape
    `UserService.confirm_email_change` uses for its own race.

    `available_at=None` means due now by the database's own clock - the clock
    `claim_outbox` compares against - so an application host running slightly
    ahead of the database cannot write a row that is not yet claimable when
    its own trigger arrives. `submitted=True` is for a caller that submits
    the row itself once its transaction commits, so the poll does not submit
    it a second time.
    """
    outbox = DispatchOutbox(
        organization_id=organization_id,
        workflow_run_id=workflow_run_id,
        node_run_id=node_run_id,
        available_at=func.now() if available_at is None else available_at,
        submitted_at=func.now() if submitted else None,
    )
    db.add(outbox)
    await db.flush()
    await db.refresh(outbox)
    return outbox


async def claim_outbox(
    db: AsyncSession, *, node_run_id: UUID, token: UUID, lease_expires_at: datetime
) -> DispatchOutbox | None:
    """The compare-and-swap claim: a `pending` row, or a `claimed` one whose lease expired.

    Matched on `node_run_id` rather than the outbox row's own id - the
    `workflow-dispatch-node` deployment is triggered with `(workflow_run_id,
    node_run_id)`, and the partial unique index guarantees at most one live
    row per `node_run_id` to match.

    `status = 'claimed' AND lease_expires_at < now()` must be its own branch:
    `status = 'pending'` alone can never match a row this same claim already
    transitioned to `claimed`, which would permanently strand a run the
    instant its worker died mid-lease. `available_at <= now()` keeps a
    scheduled-but-not-yet-due retry from being claimed early by a direct wake
    racing the poller.
    """
    result = await db.execute(
        sql_update(DispatchOutbox)
        .where(
            DispatchOutbox.node_run_id == node_run_id,
            DispatchOutbox.available_at <= func.now(),
            (DispatchOutbox.status == DispatchOutboxStatus.PENDING.value)
            | (
                (DispatchOutbox.status == DispatchOutboxStatus.CLAIMED.value)
                & (DispatchOutbox.lease_expires_at < func.now())
            ),
        )
        .values(
            claimed_by=token,
            lease_expires_at=lease_expires_at,
            status=DispatchOutboxStatus.CLAIMED.value,
        )
        .returning(DispatchOutbox)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def take_due_for_submission(
    db: AsyncSession, *, resubmit_before: datetime, limit: int = 100
) -> list[DispatchOutbox]:
    """Deployment-wide: `pending` rows due now, stamped as submitted in the same statement.

    `workflow-dispatch-poll`'s scan. A row submitted at or after
    `resubmit_before` is left alone - its flow run is queued and will claim it
    - so a backed-up worker pool gets one submission per row per interval, not
    one per tick. `SKIP LOCKED` leaves a row a worker is claiming right now to
    that worker.

    Unscoped like `agent_run_repo.list_stale_approvals` - the poller has no
    tenant of its own - and every write it triggers is still scoped by the
    node it dispatches. Lease-expired `claimed` rows are deliberately not
    here: reclaiming one safely needs to know whether an attempt was ever
    created for it, which is `workflow-reconcile`'s job, not the fast poller's.
    """
    due = (
        select(DispatchOutbox.id)
        .where(
            DispatchOutbox.status == DispatchOutboxStatus.PENDING.value,
            DispatchOutbox.available_at <= func.now(),
            or_(
                DispatchOutbox.submitted_at.is_(None),
                DispatchOutbox.submitted_at < resubmit_before,
            ),
        )
        .order_by(DispatchOutbox.available_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return await _stamp_submitted(db, due)


async def take_stale_claims_for_resubmission(
    db: AsyncSession, *, before: datetime, resubmit_before: datetime, limit: int = 100
) -> list[DispatchOutbox]:
    """`claimed` rows past their lease with no `in_flight` attempt, stamped as submitted.

    The crash window between phase 1 (claim commits) and phase 2 (the
    `in_flight` attempt commits) - nothing was ever recorded for the
    reconciler's other query (`list_orphaned_in_flight`) to find, so this is
    the complementary scan: safe to reclaim exactly like a fresh `pending`
    row, since no call was ever made. The same once-per-interval rule as
    `take_due_for_submission` applies.
    """
    in_flight_node_runs = (
        select(NodeAttempt.node_run_id)
        .where(NodeAttempt.status == NodeAttemptStatus.IN_FLIGHT.value)
        .distinct()
    )
    stale = (
        select(DispatchOutbox.id)
        .where(
            DispatchOutbox.status == DispatchOutboxStatus.CLAIMED.value,
            DispatchOutbox.lease_expires_at.is_not(None),
            DispatchOutbox.lease_expires_at < before,
            DispatchOutbox.node_run_id.not_in(in_flight_node_runs),
            or_(
                DispatchOutbox.submitted_at.is_(None),
                DispatchOutbox.submitted_at < resubmit_before,
            ),
        )
        .order_by(DispatchOutbox.lease_expires_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return await _stamp_submitted(db, stale)


async def _stamp_submitted(db: AsyncSession, ids: Select[tuple[UUID]]) -> list[DispatchOutbox]:
    result = await db.execute(
        sql_update(DispatchOutbox)
        .where(DispatchOutbox.id.in_(ids))
        .values(submitted_at=func.now())
        .returning(DispatchOutbox)
        # A row this session already holds would otherwise come back with its
        # pre-update values.
        .execution_options(synchronize_session=False, populate_existing=True)
    )
    return list(result.scalars().all())


async def renew_lease(
    db: AsyncSession, *, node_run_id: UUID, token: UUID, lease_expires_at: datetime
) -> bool:
    """Extend a claim's lease, but only while it is still this token's open claim.

    Returns whether it was: `False` means the row was reclaimed, closed or
    cancelled since, and the holder has lost it.
    """
    result = await db.execute(
        sql_update(DispatchOutbox)
        .where(
            DispatchOutbox.node_run_id == node_run_id,
            DispatchOutbox.claimed_by == token,
            DispatchOutbox.status == DispatchOutboxStatus.CLAIMED.value,
        )
        .values(lease_expires_at=lease_expires_at)
        .returning(DispatchOutbox.id)
        .execution_options(synchronize_session=False)
    )
    return result.first() is not None


async def mark_outbox_done(db: AsyncSession, *, outbox: DispatchOutbox) -> DispatchOutbox:
    outbox.status = DispatchOutboxStatus.DONE.value
    db.add(outbox)
    await db.flush()
    await db.refresh(outbox)
    return outbox


async def get_outbox_for_node_run(db: AsyncSession, *, node_run_id: UUID) -> DispatchOutbox | None:
    result = await db.execute(
        select(DispatchOutbox)
        .where(DispatchOutbox.node_run_id == node_run_id)
        .order_by(DispatchOutbox.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_outbox_for_node_run_for_update(
    db: AsyncSession, *, node_run_id: UUID
) -> DispatchOutbox | None:
    """The same row `get_outbox_for_node_run` reads, held for the caller's transaction.

    `begin_attempt`'s own fencing-token check is a plain read otherwise - true
    at the instant it runs, but not for the rest of that transaction, so a
    worker that stalls *after* passing it (resolving the graph, io and auth
    context, all before `create_attempt`) could still commit an attempt after
    a reclaim changed `claimed_by` out from under it. Locking this row for the
    whole of `begin_attempt` makes `claim_outbox`'s own CAS `UPDATE` - which
    needs the same row - wait for that transaction to end rather than race it,
    so the check stays true for as long as it needs to matter.
    """
    result = await db.execute(
        select(DispatchOutbox)
        .where(DispatchOutbox.node_run_id == node_run_id)
        .order_by(DispatchOutbox.created_at.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def has_live_outbox(db: AsyncSession, *, workflow_run_id: UUID) -> bool:
    """Whether any `pending`/`claimed` dispatch row remains for this run.

    What `WorkflowRunStatus.SUCCEEDED`'s "no rows" actually means - not that
    none exist at all (`done`/`cancelled` rows are kept, not deleted, for
    audit and reconciliation), only that nothing is left to dispatch.
    """
    result = await db.execute(
        select(DispatchOutbox.id)
        .where(
            DispatchOutbox.workflow_run_id == workflow_run_id,
            DispatchOutbox.status.in_(
                [DispatchOutboxStatus.PENDING.value, DispatchOutboxStatus.CLAIMED.value]
            ),
        )
        .limit(1)
    )
    return result.first() is not None


async def cancel_live_outbox_for_run(db: AsyncSession, *, workflow_run_id: UUID) -> Sequence[UUID]:
    """Cancel every `pending` or `claimed` outbox row for a run. Returns the ids touched."""
    result = await db.execute(
        sql_update(DispatchOutbox)
        .where(
            DispatchOutbox.workflow_run_id == workflow_run_id,
            DispatchOutbox.status.in_(
                [DispatchOutboxStatus.PENDING.value, DispatchOutboxStatus.CLAIMED.value]
            ),
        )
        .values(status=DispatchOutboxStatus.CANCELLED.value)
        .returning(DispatchOutbox.id)
    )
    return result.scalars().all()


# WorkflowEvent


async def append_event(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    kind: str,
    node_run_id: UUID | None,
    payload: dict[str, Any],
) -> WorkflowEvent:
    """Append one event, consuming the run's own `next_event_seq`.

    The caller must already hold `run` from this transaction (typically row-
    locked via `get_run_for_update`) - the seq bump and the insert share this
    one flush, which is what keeps the counter and the row it numbers from
    disagreeing.

    `run` is refreshed as well as the event: the flush fires
    `TimestampMixin.updated_at`'s `onupdate`, which expires that attribute, and
    a caller reading it afterwards (the facade's own response) would otherwise
    lazy-load on an async session and raise `MissingGreenlet`.
    """
    seq = run.next_event_seq
    run.next_event_seq = seq + 1
    event = WorkflowEvent(
        organization_id=run.organization_id,
        workflow_run_id=run.id,
        seq=seq,
        kind=kind,
        node_run_id=node_run_id,
        payload=payload,
    )
    db.add(event)
    db.add(run)
    await db.flush()
    await db.refresh(event)
    await db.refresh(run)
    return event


async def list_events_since(
    db: AsyncSession,
    *,
    workflow_run_id: UUID,
    organization_id: UUID,
    after_seq: int | None,
    limit: int = 100,
) -> list[WorkflowEvent]:
    where = [
        WorkflowEvent.workflow_run_id == workflow_run_id,
        WorkflowEvent.organization_id == organization_id,
    ]
    if after_seq is not None:
        where.append(WorkflowEvent.seq > after_seq)
    result = await db.execute(
        select(WorkflowEvent).where(*where).order_by(WorkflowEvent.seq).limit(limit)
    )
    return list(result.scalars().all())


# ResourceRef


async def create_resource_ref(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_run_id: UUID,
    kind: str,
    ref: dict[str, Any],
) -> ResourceRef:
    resource_ref = ResourceRef(
        organization_id=organization_id, workflow_run_id=workflow_run_id, kind=kind, ref=ref
    )
    db.add(resource_ref)
    await db.flush()
    await db.refresh(resource_ref)
    return resource_ref


async def list_resource_refs(db: AsyncSession, *, workflow_run_id: UUID) -> list[ResourceRef]:
    result = await db.execute(
        select(ResourceRef).where(ResourceRef.workflow_run_id == workflow_run_id)
    )
    return list(result.scalars().all())
