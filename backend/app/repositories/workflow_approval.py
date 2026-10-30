"""The decisions workflow runs wait on (`human.approval`), and the steps parked on them."""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal, NamedTuple
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow import Workflow
from app.db.models.workflow_approval import (
    ProposalFormat,
    WorkflowApproval,
    WorkflowApprovalStatus,
)
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeRun,
    NodeRunStatus,
    WaitingReason,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.repositories import workflow as workflow_repo

OutcomeLevel = Literal["total", "step", "workflow"]


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
    workflow_run_id: UUID,
    node_run_id: UUID,
    title: str,
    details: str | None,
    approver_user_ids: list[UUID],
    expires_at: datetime | None,
    editable: bool = False,
    proposal: str | None = None,
    proposal_format: ProposalFormat = "text",
    proposal_label: str | None = None,
    choices: list[dict[str, str]] | None = None,
) -> WorkflowApproval:
    row = WorkflowApproval(
        organization_id=organization_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        node_run_id=node_run_id,
        title=title,
        details=details,
        approver_user_ids=[str(user_id) for user_id in approver_user_ids],
        expires_at=expires_at,
        editable=editable,
        proposal=proposal,
        proposal_format=proposal_format,
        proposal_label=proposal_label,
        choices=choices,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_for_node_run_for_update(
    db: AsyncSession, node_run_id: UUID
) -> WorkflowApproval | None:
    """The request one step's run made, if it has made one, locked while the step reads it."""
    query = (
        select(WorkflowApproval)
        .where(WorkflowApproval.node_run_id == node_run_id)
        .with_for_update()
    )
    return (await db.execute(query)).scalar_one_or_none()


async def has_pending(db: AsyncSession, node_run_id: UUID) -> bool:
    """Whether this step's request is still waiting on a decision."""
    found = await db.execute(
        select(WorkflowApproval.id).where(
            WorkflowApproval.node_run_id == node_run_id,
            WorkflowApproval.status == WorkflowApprovalStatus.PENDING.value,
        )
    )
    return found.first() is not None


async def get_for_update(
    db: AsyncSession, approval_id: UUID, *, organization_id: UUID
) -> WorkflowApproval | None:
    """One request in this organization, locked for its decision."""
    result = await db.execute(
        select(WorkflowApproval)
        .where(
            WorkflowApproval.id == approval_id,
            WorkflowApproval.organization_id == organization_id,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def list_with_workflow(
    db: AsyncSession,
    *,
    organization_id: UUID,
    statuses: list[str],
    skip: int,
    limit: int,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    oldest_first: bool = True,
) -> tuple[list[tuple[WorkflowApproval, str]], int]:
    """One organization's requests in `statuses`, each with its workflow's name.

    Oldest first unless `oldest_first` is false, and narrowed to those asked
    within `created_from` .. `created_to` when given.
    """
    where = [
        WorkflowApproval.organization_id == organization_id,
        WorkflowApproval.status.in_(statuses),
    ]
    if created_from is not None:
        where.append(WorkflowApproval.created_at >= created_from)
    if created_to is not None:
        where.append(WorkflowApproval.created_at <= created_to)
    ordering = (
        (WorkflowApproval.created_at, WorkflowApproval.id)
        if oldest_first
        else (WorkflowApproval.created_at.desc(), WorkflowApproval.id.desc())
    )
    total = await db.scalar(select(func.count()).select_from(WorkflowApproval).where(*where))
    rows = await db.execute(
        select(WorkflowApproval, Workflow.name)
        .join(Workflow, Workflow.id == WorkflowApproval.workflow_id)
        .where(*where)
        .order_by(*ordering)
        .offset(skip)
        .limit(limit)
    )
    return [(approval, name) for approval, name in rows.all()], total or 0


async def update(
    db: AsyncSession, *, approval: WorkflowApproval, update_data: dict[str, object]
) -> WorkflowApproval:
    for field, value in update_data.items():
        setattr(approval, field, value)
    await db.flush()
    await db.refresh(approval)
    return approval


async def cancel_pending_for_run(db: AsyncSession, workflow_run_id: UUID) -> None:
    """Close every request a cancelled run left waiting, so none is decided for nothing."""
    await db.execute(
        sql_update(WorkflowApproval)
        .where(
            WorkflowApproval.workflow_run_id == workflow_run_id,
            WorkflowApproval.status == WorkflowApprovalStatus.PENDING.value,
        )
        .values(status=WorkflowApprovalStatus.CANCELLED.value)
    )


async def cancel_pending_for_node_runs(db: AsyncSession, node_run_ids: Sequence[UUID]) -> None:
    """Close the requests of steps that were stopped, so none is decided for nothing."""
    await db.execute(
        sql_update(WorkflowApproval)
        .where(
            WorkflowApproval.node_run_id.in_(node_run_ids),
            WorkflowApproval.status == WorkflowApprovalStatus.PENDING.value,
        )
        .values(status=WorkflowApprovalStatus.CANCELLED.value)
    )


async def list_stale_waits(db: AsyncSession, *, now: datetime, limit: int = 100) -> list[NodeRun]:
    """Steps parked on a request that was decided, or ran out of time, with no wake queued.

    The reconciler's backstop for the direct wake a decision queues after its
    commit: a lost wake leaves exactly this shape - a waiting step whose request
    is no longer pending, or is pending past its expiry, and no live dispatch
    row. A run already over is left alone; nothing it waits on matters to it.
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
    terminal_statuses = [status.value for status in WorkflowRunStatus if status.is_terminal]
    result = await db.execute(
        select(NodeRun)
        .join(WorkflowApproval, WorkflowApproval.node_run_id == NodeRun.id)
        .join(WorkflowRun, WorkflowRun.id == NodeRun.workflow_run_id)
        .where(
            NodeRun.status == NodeRunStatus.WAITING.value,
            NodeRun.waiting_reason == WaitingReason.APPROVAL.value,
            NodeRun.waiting_agent_run_id.is_(None),
            WorkflowRun.status.not_in(terminal_statuses),
            or_(
                WorkflowApproval.status != WorkflowApprovalStatus.PENDING.value,
                WorkflowApproval.expires_at <= now,
            ),
            NodeRun.id.not_in(live_outbox),
        )
        # By run id, for the same lock-order reason as the other sweeps.
        .order_by(NodeRun.workflow_run_id, NodeRun.id)
        .limit(limit)
    )
    return list(result.scalars().all())


class OutcomeFigures(NamedTuple):
    """One level key's approval outcomes: counts, time to decide and the edit-ratio buckets.

    `workflow_id` and `name` are set at the `workflow` level, `node_instance_id` at the
    `step` level; the `total` level leaves all three `None`. The quantiles are `None`
    when no row feeds them.
    """

    workflow_id: UUID | None
    name: str | None
    node_instance_id: UUID | None
    requests: int
    pending: int
    approved_unchanged: int
    approved_edited: int
    rejected: int
    expired: int
    cancelled: int
    decide_p50: float | None
    decide_p95: float | None
    edit_ratio_median: float | None
    b0: int
    b10: int
    b25: int
    b50: int
    b100: int


class OutcomeDay(NamedTuple):
    """How many requests created on one UTC day ended one way (`edited` as decided)."""

    day: date
    status: str
    edited: bool
    count: int


async def outcome_figures(
    db: AsyncSession,
    *,
    organization_id: UUID,
    since: datetime,
    until: datetime | None,
    level: OutcomeLevel,
    workflow_id: UUID | None = None,
    visible_to_user_id: UUID | None = None,
    shared_ids: list[UUID] | None = None,
) -> list[OutcomeFigures]:
    """What the requests of real runs created in `[since, until)` came to, per `level`.

    One row for the whole selection at `total`, one per approval step at `step`
    (keyed by the step's `node_instance_id`) and one per workflow at `workflow`.
    `workflow_id` narrows to one workflow; `visible_to_user_id` narrows to the
    workflows `workflow_repo.visible_to` lets that user see, given `shared_ids`
    (omit it to see them all). Quantiles cannot be summed across rows, so each
    level is its own aggregate query.
    """
    approval = WorkflowApproval
    approved = WorkflowApprovalStatus.APPROVED.value
    rejected = WorkflowApprovalStatus.REJECTED.value
    took = func.extract("epoch", approval.decided_at - approval.created_at)
    ratio = approval.edit_ratio

    def count(*conditions: ColumnElement[bool]) -> ColumnElement[int]:
        return func.count().filter(*conditions)

    def of_status(value: WorkflowApprovalStatus) -> ColumnElement[bool]:
        return approval.status == value.value

    figures = (
        func.count(),
        count(of_status(WorkflowApprovalStatus.PENDING)),
        count(approval.status == approved, approval.edited.is_(False)),
        count(approval.status == approved, approval.edited.is_(True)),
        count(approval.status == rejected),
        count(of_status(WorkflowApprovalStatus.EXPIRED)),
        count(of_status(WorkflowApprovalStatus.CANCELLED)),
        func.percentile_cont(0.5)
        .within_group(took)
        .filter(approval.status.in_([approved, rejected])),
        func.percentile_cont(0.95)
        .within_group(took)
        .filter(approval.status.in_([approved, rejected])),
        func.percentile_cont(0.5)
        .within_group(ratio)
        .filter(approval.edited.is_(True), ratio.is_not(None)),
        count(ratio == 0),
        count(ratio > 0, ratio <= 0.1),
        count(ratio > 0.1, ratio <= 0.25),
        count(ratio > 0.25, ratio <= 0.5),
        count(ratio > 0.5),
    )
    query = (
        select(*figures)
        .select_from(approval)
        .join(WorkflowRun, WorkflowRun.id == approval.workflow_run_id)
        .where(
            approval.organization_id == organization_id,
            WorkflowRun.organization_id == organization_id,
            WorkflowRun.mode == "real",
            approval.created_at >= since,
        )
    )
    if until is not None:
        query = query.where(approval.created_at < until)
    if workflow_id is not None:
        query = query.where(approval.workflow_id == workflow_id)
    if visible_to_user_id is not None:
        visible = select(Workflow.id).where(
            Workflow.organization_id == organization_id,
            workflow_repo.visible_to(user_id=visible_to_user_id, shared_ids=shared_ids or []),
        )
        query = query.where(approval.workflow_id.in_(visible))
    if level == "total":
        rows = (await db.execute(query)).all()
        return [OutcomeFigures(None, None, None, *row) for row in rows]
    if level == "step":
        query = query.add_columns(NodeRun.node_instance_id).join(
            NodeRun, NodeRun.id == approval.node_run_id
        )
        query = query.group_by(NodeRun.node_instance_id)
        return [
            OutcomeFigures(None, None, row[-1], *row[:-1])
            for row in (await db.execute(query)).all()
        ]
    query = (
        query.add_columns(approval.workflow_id, Workflow.name)
        .join(
            Workflow,
            (Workflow.id == approval.workflow_id) & (Workflow.organization_id == organization_id),
        )
        .group_by(approval.workflow_id, Workflow.name)
    )
    return [
        OutcomeFigures(row[-2], row[-1], None, *row[:-2]) for row in (await db.execute(query)).all()
    ]


async def outcome_days(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID, since: datetime
) -> list[OutcomeDay]:
    """One workflow's requests of real runs created since `since`, counted by UTC day
    of the request, decision and whether the approver edited."""
    day = func.date(func.timezone("UTC", WorkflowApproval.created_at))
    result = await db.execute(
        select(day, WorkflowApproval.status, WorkflowApproval.edited, func.count())
        .join(WorkflowRun, WorkflowRun.id == WorkflowApproval.workflow_run_id)
        .where(
            WorkflowApproval.organization_id == organization_id,
            WorkflowApproval.workflow_id == workflow_id,
            WorkflowRun.organization_id == organization_id,
            WorkflowRun.mode == "real",
            WorkflowApproval.created_at >= since,
        )
        .group_by(day, WorkflowApproval.status, WorkflowApproval.edited)
    )
    return [
        OutcomeDay(row_day, row_status, bool(edited), int(total))
        for row_day, row_status, edited, total in result.all()
    ]
