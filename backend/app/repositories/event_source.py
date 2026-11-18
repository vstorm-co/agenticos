"""Database operations for source admission and independent subscriber receipts."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import String, cast, delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_job import BackgroundJob
from app.db.models.event_source import (
    EventDelivery,
    EventDispatch,
    EventSource,
    EventSourceCredential,
    EventSubscription,
)


async def get(
    db: AsyncSession, source_id: UUID, *, organization_id: UUID | None = None, lock: bool = False
) -> EventSource | None:
    query = select(EventSource).where(EventSource.id == source_id)
    if organization_id is not None:
        query = query.where(EventSource.organization_id == organization_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def list_sources(db: AsyncSession, *, organization_id: UUID) -> list[EventSource]:
    return list(
        (
            await db.scalars(
                select(EventSource)
                .where(EventSource.organization_id == organization_id)
                .order_by(EventSource.name, EventSource.id)
            )
        ).all()
    )


async def save[R: EventSource | EventSourceCredential | EventSubscription | EventDispatch](
    db: AsyncSession, row: R
) -> R:
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def credential(
    db: AsyncSession, secret_id: UUID, *, organization_id: UUID
) -> EventSourceCredential | None:
    return await db.scalar(
        select(EventSourceCredential).where(
            EventSourceCredential.id == secret_id,
            EventSourceCredential.organization_id == organization_id,
        )
    )


async def subscriptions(
    db: AsyncSession, source_id: UUID, *, organization_id: UUID
) -> list[EventSubscription]:
    return list(
        (
            await db.scalars(
                select(EventSubscription).where(
                    EventSubscription.source_id == source_id,
                    EventSubscription.organization_id == organization_id,
                )
            )
        ).all()
    )


async def unbind(db: AsyncSession, *, exposure_id: UUID) -> None:
    await db.execute(delete(EventSubscription).where(EventSubscription.exposure_id == exposure_id))
    await db.flush()


async def delete_source(db: AsyncSession, row: EventSource) -> None:
    secret_id = row.secret_id
    await db.delete(row)
    await db.flush()
    await db.execute(
        delete(EventSourceCredential).where(
            EventSourceCredential.id == secret_id,
            EventSourceCredential.organization_id == row.organization_id,
        )
    )


async def admit(db: AsyncSession, delivery: EventDelivery) -> bool:
    """One insert claims an external ID concurrently; NULL IDs never deduplicate."""
    result = await db.scalar(
        insert(EventDelivery)
        .values(
            id=delivery.id,
            organization_id=delivery.organization_id,
            source_id=delivery.source_id,
            external_id=delivery.external_id,
            body=delivery.body,
            headers=delivery.headers,
        )
        .on_conflict_do_nothing(constraint="uq_event_delivery_source_external")
        .returning(EventDelivery.id)
    )
    return result is not None


async def dispatch(
    db: AsyncSession, dispatch_id: UUID, *, organization_id: UUID
) -> EventDispatch | None:
    return await db.scalar(
        select(EventDispatch)
        .where(EventDispatch.id == dispatch_id, EventDispatch.organization_id == organization_id)
        .with_for_update()
    )


async def delivery(
    db: AsyncSession, delivery_id: UUID, *, organization_id: UUID
) -> EventDelivery | None:
    return await db.scalar(
        select(EventDelivery).where(
            EventDelivery.id == delivery_id, EventDelivery.organization_id == organization_id
        )
    )


async def subscription(
    db: AsyncSession, subscription_id: UUID, *, organization_id: UUID
) -> EventSubscription | None:
    return await db.scalar(
        select(EventSubscription).where(
            EventSubscription.id == subscription_id,
            EventSubscription.organization_id == organization_id,
        )
    )


async def clear_terminal_payloads(db: AsyncSession, *, before: datetime) -> None:
    """Keep payloads while any dispatch still needs them; terminal copies expire."""
    pending = exists(
        select(EventDispatch.id).where(
            EventDispatch.delivery_id == EventDelivery.id, EventDispatch.status == "pending"
        )
    )
    await db.execute(
        update(EventDelivery)
        .where(EventDelivery.created_at < before, ~pending, EventDelivery.body.is_not(None))
        .values(body=None, headers={})
    )


async def target_subscription(
    db: AsyncSession, *, trigger_id: UUID | None = None, exposure_id: UUID | None = None
) -> EventSubscription | None:
    target = (
        EventSubscription.trigger_id == trigger_id
        if trigger_id
        else EventSubscription.exposure_id == exposure_id
    )
    return await db.scalar(select(EventSubscription).where(target))


async def settle_abandoned_dispatches(db: AsyncSession, *, before: datetime) -> None:
    """Terminal or already-purged jobs cannot keep a payload forever; live jobs can."""
    live_job = exists(
        select(BackgroundJob.id).where(
            BackgroundJob.kind == "dispatch-source-event",
            BackgroundJob.organization_id == EventDispatch.organization_id,
            BackgroundJob.payload["dispatch_id"].astext == cast(EventDispatch.id, String),
            BackgroundJob.status.in_(("queued", "running")),
        )
    )
    await db.execute(
        update(EventDispatch)
        .where(EventDispatch.status == "pending", EventDispatch.created_at < before, ~live_job)
        .values(status="failed", error_code="DISPATCH_JOB_TERMINAL", completed_at=datetime.now(UTC))
    )
