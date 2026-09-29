"""Workflow exposures and their webhook deliveries (#1792)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_exposure import (
    ExposureAdapter,
    WorkflowExposure,
    WorkflowWebhookDelivery,
)

# The advisory-lock namespace one webhook delivery id is serialized under, apart
# from the admission locks' own (`workflow_run._ORG_ADMISSION_LOCK_NAMESPACE`).
_DELIVERY_LOCK_NAMESPACE = 1792


async def create(db: AsyncSession, **fields: Any) -> WorkflowExposure:
    exposure = WorkflowExposure(**fields)
    db.add(exposure)
    await db.flush()
    await db.refresh(exposure)
    return exposure


async def get(
    db: AsyncSession, exposure_id: UUID, *, organization_id: UUID, workflow_id: UUID
) -> WorkflowExposure | None:
    """One exposure of one workflow, in one organization."""
    result = await db.execute(
        select(WorkflowExposure).where(
            WorkflowExposure.id == exposure_id,
            WorkflowExposure.organization_id == organization_id,
            WorkflowExposure.workflow_id == workflow_id,
        )
    )
    return result.scalar_one_or_none()


async def active_by_workflow(
    db: AsyncSession, *, organization_id: UUID, workflow_ids: list[UUID]
) -> dict[UUID, bool]:
    """Whether each of these workflows' row is on, for those that have one."""
    if not workflow_ids:
        return {}
    result = await db.execute(
        select(WorkflowExposure.workflow_id, WorkflowExposure.is_active).where(
            WorkflowExposure.organization_id == organization_id,
            WorkflowExposure.workflow_id.in_(workflow_ids),
        )
    )
    return {row.workflow_id: row.is_active for row in result.all()}


async def get_for_workflow(
    db: AsyncSession, *, workflow_id: UUID, organization_id: UUID
) -> WorkflowExposure | None:
    """The workflow's exposure, if its live trigger is a webhook or a schedule."""
    result = await db.execute(
        select(WorkflowExposure).where(
            WorkflowExposure.workflow_id == workflow_id,
            WorkflowExposure.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, exposure_id: UUID) -> WorkflowExposure | None:
    """An exposure by id alone, for a webhook delivery - which carries no tenant
    header and is authenticated by the exposure's own secret instead."""
    return await db.get(WorkflowExposure, exposure_id)


async def update(
    db: AsyncSession, *, exposure: WorkflowExposure, update_data: dict[str, Any]
) -> WorkflowExposure:
    for field, value in update_data.items():
        setattr(exposure, field, value)
    await db.flush()
    await db.refresh(exposure)
    return exposure


async def delete(db: AsyncSession, *, exposure: WorkflowExposure) -> None:
    await db.delete(exposure)
    await db.flush()


async def claim_due_schedules(
    db: AsyncSession, *, now: datetime, limit: int
) -> list[WorkflowExposure]:
    """The active schedules due by `now`, locked so a second heartbeat takes none.

    `FOR UPDATE SKIP LOCKED` is the no-double-fire guard: concurrent heartbeats
    each take a disjoint set, and the caller advances `next_fire_at` under the
    same lock before its transaction commits.
    """
    result = await db.execute(
        select(WorkflowExposure)
        .where(
            WorkflowExposure.adapter == ExposureAdapter.SCHEDULE.value,
            WorkflowExposure.is_active.is_(True),
            WorkflowExposure.next_fire_at <= now,
        )
        .order_by(WorkflowExposure.next_fire_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def lock_delivery(db: AsyncSession, *, exposure_id: UUID, delivery_id: str) -> None:
    """Serialize every attempt at one delivery id until this transaction ends.

    Taken before the delivery is looked up, so a provider's retry racing its own
    first attempt waits for that attempt to commit and then finds its row,
    rather than both missing it and admitting two runs. The unique constraint
    stays the source of truth; this keeps it from being the thing that answers.
    """
    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                _DELIVERY_LOCK_NAMESPACE, func.hashtext(f"{exposure_id}:{delivery_id}")
            )
        )
    )


async def get_delivery(
    db: AsyncSession, *, exposure_id: UUID, delivery_id: str
) -> WorkflowWebhookDelivery | None:
    result = await db.execute(
        select(WorkflowWebhookDelivery).where(
            WorkflowWebhookDelivery.exposure_id == exposure_id,
            WorkflowWebhookDelivery.delivery_id == delivery_id,
        )
    )
    return result.scalar_one_or_none()


async def create_delivery(
    db: AsyncSession,
    *,
    organization_id: UUID,
    exposure_id: UUID,
    delivery_id: str,
    workflow_run_id: UUID,
) -> WorkflowWebhookDelivery:
    delivery = WorkflowWebhookDelivery(
        organization_id=organization_id,
        exposure_id=exposure_id,
        delivery_id=delivery_id,
        workflow_run_id=workflow_run_id,
    )
    db.add(delivery)
    await db.flush()
    return delivery
