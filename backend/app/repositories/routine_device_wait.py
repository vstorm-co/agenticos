"""Durable pre-execution device waits; lock the parent before changing an activation."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_trigger import AgentTrigger
from app.db.models.routine_device_wait import RoutineDeviceWait

WaitStatus = Literal["started", "cancelled", "expired"]


async def get(db: AsyncSession, activation_id: UUID) -> RoutineDeviceWait | None:
    result = await db.execute(
        select(RoutineDeviceWait)
        .where(RoutineDeviceWait.id == activation_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def park(
    db: AsyncSession,
    *,
    activation_id: UUID,
    trigger: AgentTrigger,
    user_id: UUID,
    device_id: UUID,
    intent_hash: str,
    event_context: str | None,
) -> bool:
    """Keep the first scheduled activation and every distinct incoming event.

    Parent locking and admission checks belong to the caller. Conflict never
    rewrites an existing activation or resurrects a started/cancelled one.
    """
    result = await db.execute(
        insert(RoutineDeviceWait)
        .values(
            id=activation_id,
            organization_id=trigger.organization_id,
            user_id=user_id,
            trigger_id=trigger.id,
            device_id=device_id,
            intent_hash=intent_hash,
            is_event=trigger.trigger_type == "event" and event_context is not None,
            event_context=event_context,
        )
        .on_conflict_do_nothing()
        .returning(RoutineDeviceWait.id)
    )
    await db.flush()
    return result.scalar_one_or_none() is not None


async def pending(
    db: AsyncSession, *, limit: int = 100
) -> list[tuple[RoutineDeviceWait, AgentTrigger]]:
    """Lock parents and rotate inspected rows so offline devices cannot starve others."""
    result = await db.execute(
        select(RoutineDeviceWait, AgentTrigger)
        .join(AgentTrigger, AgentTrigger.id == RoutineDeviceWait.trigger_id)
        .where(RoutineDeviceWait.status == "waiting")
        .order_by(
            func.coalesce(RoutineDeviceWait.updated_at, RoutineDeviceWait.created_at),
            RoutineDeviceWait.id,
        )
        .limit(limit)
        .with_for_update(of=AgentTrigger, skip_locked=True)
        .execution_options(populate_existing=True)
    )
    rows = [(wait, trigger) for wait, trigger in result.all()]
    if rows:
        await db.execute(
            update(RoutineDeviceWait)
            .where(RoutineDeviceWait.id.in_([wait.id for wait, _ in rows]))
            .values(updated_at=datetime.now(UTC))
        )
        await db.flush()
    return rows


async def settle(
    db: AsyncSession,
    *,
    activation_id: UUID,
    status: WaitStatus,
    reason: str | None = None,
) -> bool:
    """The started marker commits with the run's admission, before the first model call."""
    result = await db.execute(
        update(RoutineDeviceWait)
        .where(RoutineDeviceWait.id == activation_id, RoutineDeviceWait.status == "waiting")
        .values(status=status, reason=reason, event_context=None, finished_at=datetime.now(UTC))
        .returning(RoutineDeviceWait.id)
    )
    return result.scalar_one_or_none() is not None


async def cancel_for_trigger(db: AsyncSession, *, trigger_id: UUID, reason: str) -> None:
    await db.execute(
        update(RoutineDeviceWait)
        .where(RoutineDeviceWait.trigger_id == trigger_id, RoutineDeviceWait.status == "waiting")
        .values(
            status="cancelled", reason=reason, event_context=None, finished_at=datetime.now(UTC)
        )
    )
    await db.flush()


async def record_job(db: AsyncSession, *, wait: RoutineDeviceWait, job_id: UUID) -> None:
    wait.last_job_id = job_id
    await db.flush()


async def record_admission_failure(db: AsyncSession, *, wait: RoutineDeviceWait) -> None:
    """Count one dead/missing dispatch once; a clean offline check is not a failure."""
    if wait.last_job_id is not None and wait.last_failed_job_id != wait.last_job_id:
        wait.last_failed_job_id = wait.last_job_id
        wait.admission_failures += 1
        await db.flush()


async def fail(db: AsyncSession, *, wait: RoutineDeviceWait) -> None:
    wait.status = "failed"
    wait.reason = "admission_failed"
    wait.finished_at = datetime.now(UTC)
    await db.flush()


async def rebind_device(
    db: AsyncSession,
    *,
    trigger_id: UUID,
    user_id: UUID,
    previous_device_id: UUID,
    device_id: UUID,
    previous_intent: str,
    intent: str,
) -> None:
    """Move unchanged waiting events with their parent under its row lock.

    Keep event payloads and activation IDs. An edited routine's old activations
    do not match the previous intent and retain their cancellation boundary.
    """
    await db.execute(
        update(RoutineDeviceWait)
        .where(
            RoutineDeviceWait.trigger_id == trigger_id,
            RoutineDeviceWait.user_id == user_id,
            RoutineDeviceWait.device_id == previous_device_id,
            RoutineDeviceWait.intent_hash == previous_intent,
            RoutineDeviceWait.status == "waiting",
        )
        .values(device_id=device_id, intent_hash=intent)
    )
    await db.flush()
