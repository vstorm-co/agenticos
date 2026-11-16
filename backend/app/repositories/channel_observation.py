"""Transactional channel windows and seven-day native-delivery deduplication."""

import hashlib
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_exposure import AgentExposure
from app.db.models.channel_observation import ChannelObservation, ChannelObservationReceipt
from app.schemas.channel_observer import ObservedChannelMessage


async def append(
    db: AsyncSession,
    *,
    exposure: AgentExposure,
    platform_chat_id: str,
    message: ObservedChannelMessage,
    addressed: bool,
    unmentioned_minutes: int,
    mentioned_minutes: int,
    admission_hash: str,
    previously_mentioned: bool = False,
) -> bool:
    window_query = (
        select(ChannelObservation)
        .where(
            ChannelObservation.exposure_id == exposure.id,
            ChannelObservation.platform_chat_id == platform_chat_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    key = hashlib.sha256(f"{platform_chat_id}\0{message.message_id}".encode()).hexdigest()
    admitted = await db.scalar(
        insert(ChannelObservationReceipt)
        .values(
            exposure_id=exposure.id,
            message_key=key,
            expires_at=message.received_at + timedelta(days=7),
        )
        .on_conflict_do_nothing()
        .returning(ChannelObservationReceipt.message_key)
    )
    if admitted is None:
        # Adding a mention in an edit must cancel a queued automatic reply even
        # though this native message was already collected before the edit.
        if addressed:
            existing = await db.scalar(window_query)
            if existing is not None:
                existing.mentioned = True
                existing.revision += 1
                existing.checked_revision = existing.revision
                existing.next_check_at = message.received_at + timedelta(minutes=mentioned_minutes)
                await db.flush()
        return False
    due = message.received_at + timedelta(
        minutes=mentioned_minutes if previously_mentioned else unmentioned_minutes
    )
    await db.execute(
        insert(ChannelObservation)
        .values(
            id=uuid4(),
            organization_id=exposure.organization_id,
            exposure_id=exposure.id,
            generation=exposure.observation_generation,
            admission_hash=admission_hash,
            platform_chat_id=platform_chat_id,
            messages=[],
            mentioned=previously_mentioned,
            revision=0,
            checked_revision=0,
            next_check_at=due,
            updated_at=message.received_at,
        )
        .on_conflict_do_nothing(constraint="uq_channel_observation_thread")
    )
    row = (await db.scalars(window_query)).one()
    if row.generation != exposure.observation_generation or row.admission_hash != admission_hash:
        row.generation = exposure.observation_generation
        row.admission_hash = admission_hash
        row.messages = []
        row.mentioned = previously_mentioned
        row.next_check_at = due
        row.checked_revision = row.revision
    row.revision += 1
    row.updated_at = message.received_at
    row.messages = [*row.messages, message.model_dump(mode="json")][-20:]
    if addressed:
        row.mentioned = True
        # An ordinary immediate answer supersedes any queued automatic answer.
        row.checked_revision = row.revision
        row.next_check_at = message.received_at + timedelta(minutes=mentioned_minutes)
    await db.flush()
    return True


async def due(db: AsyncSession, *, now: datetime) -> list[ChannelObservation]:
    rows = await db.scalars(
        select(ChannelObservation)
        .where(
            ChannelObservation.revision > ChannelObservation.checked_revision,
            ChannelObservation.next_check_at <= now,
        )
        .order_by(ChannelObservation.next_check_at)
        .limit(50)
        .with_for_update(skip_locked=True)
    )
    return list(rows.all())


async def get(
    db: AsyncSession,
    *,
    observation_id: UUID,
    organization_id: UUID,
    for_update: bool = False,
) -> ChannelObservation | None:
    query = (
        select(ChannelObservation)
        .where(
            ChannelObservation.id == observation_id,
            ChannelObservation.organization_id == organization_id,
        )
        .execution_options(populate_existing=True)
    )
    if for_update:
        query = query.with_for_update()
    return await db.scalar(query)


async def expire(db: AsyncSession, *, now: datetime) -> None:
    await db.execute(
        delete(ChannelObservationReceipt).where(
            ChannelObservationReceipt.expires_at <= now,
        )
    )
    await db.execute(
        delete(ChannelObservation).where(
            ChannelObservation.updated_at < now - timedelta(days=7),
        )
    )


async def claim_analysis(
    db: AsyncSession,
    *,
    observation_id: UUID,
    organization_id: UUID,
    generation: UUID,
    revision: int,
) -> bool:
    """Spend each window at most once, including after a worker loses its lease."""
    claimed = await db.scalar(
        update(ChannelObservation)
        .where(
            ChannelObservation.id == observation_id,
            ChannelObservation.organization_id == organization_id,
            ChannelObservation.generation == generation,
            ChannelObservation.checked_revision == revision,
            ChannelObservation.started_revision < revision,
        )
        .values(started_revision=revision)
        .returning(ChannelObservation.id)
    )
    return claimed is not None
