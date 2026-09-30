"""Table triggers, their revisions and admissions, and the outbox they consume (#1785)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.virtual_table import VirtualTableOutbox, VirtualTableRecordHistory
from app.db.models.virtual_table_trigger import (
    TableTriggerAdmission,
    VirtualTableTrigger,
    VirtualTableTriggerRevision,
)

CREATED_EVENT = "table.record.created"


def activation_time() -> ColumnElement[datetime]:
    """The moment a trigger comes on, on the database's clock - the one an outbox
    row is stamped with, so the two compare without any host's clock between them."""
    return func.clock_timestamp()


async def create(db: AsyncSession, **fields: Any) -> VirtualTableTrigger:
    trigger = VirtualTableTrigger(**fields)
    db.add(trigger)
    await db.flush()
    await db.refresh(trigger)
    return trigger


async def add_revision(db: AsyncSession, *, trigger: VirtualTableTrigger) -> None:
    """Freeze what the trigger is now, so a decision made under it can be traced."""
    db.add(
        VirtualTableTriggerRevision(
            trigger_id=trigger.id,
            revision=trigger.revision,
            workflow_version_id=trigger.workflow_version_id,
            filters=trigger.filters,
            execution_principal_user_id=trigger.execution_principal_user_id,
        )
    )
    await db.flush()


async def get(
    db: AsyncSession, trigger_id: UUID, *, organization_id: UUID, table_id: UUID
) -> VirtualTableTrigger | None:
    result = await db.execute(
        select(VirtualTableTrigger).where(
            VirtualTableTrigger.id == trigger_id,
            VirtualTableTrigger.organization_id == organization_id,
            VirtualTableTrigger.table_id == table_id,
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
        select(VirtualTableTrigger.workflow_id, VirtualTableTrigger.is_active).where(
            VirtualTableTrigger.organization_id == organization_id,
            VirtualTableTrigger.workflow_id.in_(workflow_ids),
        )
    )
    return {row.workflow_id: row.is_active for row in result.all()}


async def get_for_workflow(
    db: AsyncSession, *, workflow_id: UUID, organization_id: UUID
) -> VirtualTableTrigger | None:
    """The workflow's table trigger, if its live trigger is a new table record."""
    result = await db.execute(
        select(VirtualTableTrigger).where(
            VirtualTableTrigger.workflow_id == workflow_id,
            VirtualTableTrigger.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def lock_active(db: AsyncSession, *, trigger_id: UUID) -> VirtualTableTrigger | None:
    """The trigger as it is now, locked for the caller's transaction - `None` once
    it is switched off or gone. `populate_existing`: a copy of the row already in
    the session is overwritten with what the lock read, not trusted."""
    result = await db.execute(
        select(VirtualTableTrigger)
        .where(VirtualTableTrigger.id == trigger_id, VirtualTableTrigger.is_active.is_(True))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def list_for_table(
    db: AsyncSession, *, table_id: UUID, organization_id: UUID, active_only: bool = False
) -> list[VirtualTableTrigger]:
    query = select(VirtualTableTrigger).where(
        VirtualTableTrigger.table_id == table_id,
        VirtualTableTrigger.organization_id == organization_id,
    )
    if active_only:
        query = query.where(VirtualTableTrigger.is_active.is_(True))
    result = await db.execute(
        query.order_by(VirtualTableTrigger.created_at, VirtualTableTrigger.id)
    )
    return list(result.scalars().all())


async def update(
    db: AsyncSession, *, trigger: VirtualTableTrigger, update_data: dict[str, Any]
) -> VirtualTableTrigger:
    for field, value in update_data.items():
        setattr(trigger, field, value)
    await db.flush()
    await db.refresh(trigger)
    return trigger


async def delete(db: AsyncSession, *, trigger: VirtualTableTrigger) -> None:
    await db.delete(trigger)
    await db.flush()


async def claim_pending(db: AsyncSession, *, limit: int) -> list[VirtualTableOutbox]:
    """Undelivered record-created events, oldest first, locked against a second consumer."""
    result = await db.execute(
        select(VirtualTableOutbox)
        .where(
            VirtualTableOutbox.dispatched_at.is_(None),
            VirtualTableOutbox.event_type == CREATED_EVENT,
        )
        .order_by(VirtualTableOutbox.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def mark_dispatched(db: AsyncSession, *, event: VirtualTableOutbox, now: datetime) -> None:
    event.dispatched_at = now
    event.attempts = event.attempts + 1
    await db.flush()


async def creation_snapshot(
    db: AsyncSession, *, record_id: UUID, revision: int
) -> VirtualTableRecordHistory | None:
    """The record as it was created: the values and the author that one history row keeps."""
    result = await db.execute(
        select(VirtualTableRecordHistory).where(
            VirtualTableRecordHistory.record_id == record_id,
            VirtualTableRecordHistory.revision == revision,
            VirtualTableRecordHistory.operation == "create",
        )
    )
    return result.scalar_one_or_none()


async def admitted(db: AsyncSession, *, trigger_id: UUID, event_id: UUID) -> bool:
    result = await db.execute(
        select(TableTriggerAdmission.id).where(
            TableTriggerAdmission.trigger_id == trigger_id,
            TableTriggerAdmission.outbox_event_id == event_id,
        )
    )
    return result.first() is not None


async def add_admission(db: AsyncSession, **fields: Any) -> TableTriggerAdmission:
    admission = TableTriggerAdmission(**fields)
    db.add(admission)
    await db.flush()
    return admission


async def list_admissions(
    db: AsyncSession, *, trigger_id: UUID, skip: int, limit: int
) -> tuple[list[TableTriggerAdmission], int]:
    total = await db.scalar(
        select(func.count())
        .select_from(TableTriggerAdmission)
        .where(TableTriggerAdmission.trigger_id == trigger_id)
    )
    result = await db.execute(
        select(TableTriggerAdmission)
        .where(TableTriggerAdmission.trigger_id == trigger_id)
        .order_by(TableTriggerAdmission.created_at.desc(), TableTriggerAdmission.id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), int(total or 0)
