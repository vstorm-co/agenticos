"""Persistence for a model step's eval cases and the tries of them."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_eval import WorkflowEvalRun, WorkflowStepEval


async def list_cases(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID, node_instance_id: UUID
) -> list[WorkflowStepEval]:
    """One step's cases, oldest first."""
    result = await db.execute(
        select(WorkflowStepEval)
        .where(
            WorkflowStepEval.organization_id == organization_id,
            WorkflowStepEval.workflow_id == workflow_id,
            WorkflowStepEval.node_instance_id == node_instance_id,
        )
        .order_by(WorkflowStepEval.position)
    )
    return list(result.scalars())


async def last_position(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID, node_instance_id: UUID
) -> int:
    """The position of the step's last case, or 0 when it has none."""
    return int(
        await db.scalar(
            select(func.coalesce(func.max(WorkflowStepEval.position), 0)).where(
                WorkflowStepEval.organization_id == organization_id,
                WorkflowStepEval.workflow_id == workflow_id,
                WorkflowStepEval.node_instance_id == node_instance_id,
            )
        )
        or 0
    )


async def count_cases(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID, node_instance_id: UUID
) -> int:
    return int(
        await db.scalar(
            select(func.count()).where(
                WorkflowStepEval.organization_id == organization_id,
                WorkflowStepEval.workflow_id == workflow_id,
                WorkflowStepEval.node_instance_id == node_instance_id,
            )
        )
        or 0
    )


async def get_case(
    db: AsyncSession, case_id: UUID, *, organization_id: UUID, workflow_id: UUID
) -> WorkflowStepEval | None:
    result = await db.execute(
        select(WorkflowStepEval).where(
            WorkflowStepEval.id == case_id,
            WorkflowStepEval.organization_id == organization_id,
            WorkflowStepEval.workflow_id == workflow_id,
        )
    )
    return result.scalar_one_or_none()


async def create_case(db: AsyncSession, **fields: Any) -> WorkflowStepEval:
    case = WorkflowStepEval(**fields)
    db.add(case)
    await db.flush()
    await db.refresh(case)
    return case


async def delete_case(db: AsyncSession, *, case: WorkflowStepEval) -> None:
    await db.delete(case)
    await db.flush()


async def create_run(db: AsyncSession, **fields: Any) -> WorkflowEvalRun:
    run = WorkflowEvalRun(**fields)
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def get_run(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID, workflow_id: UUID
) -> WorkflowEvalRun | None:
    result = await db.execute(
        select(WorkflowEvalRun).where(
            WorkflowEvalRun.id == run_id,
            WorkflowEvalRun.organization_id == organization_id,
            WorkflowEvalRun.workflow_id == workflow_id,
        )
    )
    return result.scalar_one_or_none()


async def latest_run(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID, node_instance_id: UUID
) -> WorkflowEvalRun | None:
    result = await db.execute(
        select(WorkflowEvalRun)
        .where(
            WorkflowEvalRun.organization_id == organization_id,
            WorkflowEvalRun.workflow_id == workflow_id,
            WorkflowEvalRun.node_instance_id == node_instance_id,
        )
        .order_by(WorkflowEvalRun.created_at.desc(), WorkflowEvalRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
