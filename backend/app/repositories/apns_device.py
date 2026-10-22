"""Data access for iPhones' APNs device tokens (PostgreSQL async)."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.apns_device import ApnsDevice


async def upsert(db: AsyncSession, *, user_id: uuid.UUID, token: str) -> None:
    """Keep this iPhone's token for this person. An iPhone now signed in as
    somebody else becomes theirs."""
    await db.execute(
        insert(ApnsDevice)
        .values(id=uuid.uuid4(), token=token, user_id=user_id)
        .on_conflict_do_update(index_elements=[ApnsDevice.token], set_={"user_id": user_id})
    )
    await db.flush()


async def delete_for_user(db: AsyncSession, *, user_id: uuid.UUID, token: str) -> bool:
    """Forget one of this person's iPhones. Whether there was one to forget."""
    result = await db.execute(
        delete(ApnsDevice).where(ApnsDevice.user_id == user_id, ApnsDevice.token == token)
    )
    await db.flush()
    return bool(getattr(result, "rowcount", 0))


async def delete_by_id(db: AsyncSession, device_id: uuid.UUID) -> None:
    await db.execute(delete(ApnsDevice).where(ApnsDevice.id == device_id))
    await db.flush()


async def list_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[ApnsDevice]:
    result = await db.execute(
        select(ApnsDevice).where(ApnsDevice.user_id == user_id).order_by(ApnsDevice.created_at)
    )
    return list(result.scalars().all())


async def subscribed(db: AsyncSession, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these people have at least one iPhone to push to."""
    if not user_ids:
        return set()
    result = await db.execute(
        select(ApnsDevice.user_id).where(ApnsDevice.user_id.in_(user_ids)).distinct()
    )
    return set(result.scalars().all())


async def mark_sent(db: AsyncSession, device_id: uuid.UUID, at: datetime) -> None:
    await db.execute(update(ApnsDevice).where(ApnsDevice.id == device_id).values(last_sent_at=at))
    await db.flush()
