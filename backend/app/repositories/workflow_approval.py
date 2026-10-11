"""The decisions workflow runs wait on (`human.approval`), and the steps parked on them."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow import Workflow
from app.db.models.workflow_approval import WorkflowApproval, WorkflowApprovalStatus
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeRun,
    NodeRunStatus,
    WaitingReason,
    WorkflowRun,
    WorkflowRunStatus,
)


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
) -> tuple[list[tuple[WorkflowApproval, str]], int]:
    """One organization's requests in `statuses`, oldest first, each with its workflow's name."""
    where = (
        WorkflowApproval.organization_id == organization_id,
        WorkflowApproval.status.in_(statuses),
    )
    total = await db.scalar(select(func.count()).select_from(WorkflowApproval).where(*where))
    rows = await db.execute(
        select(WorkflowApproval, Workflow.name)
        .join(Workflow, Workflow.id == WorkflowApproval.workflow_id)
        .where(*where)
        .order_by(WorkflowApproval.created_at, WorkflowApproval.id)
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
