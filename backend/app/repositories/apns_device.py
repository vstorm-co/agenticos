"""Data access for iPhones' APNs device tokens (PostgreSQL async)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.apns_device import ApnsDevice
from app.db.models.session import Session


def _deliverable() -> ColumnElement[bool]:
    """Linked devices stop receiving push when their sign-in ends.

    Existing subscriptions without a recorded session retain their standing
    permission; new registrations are linked by the authenticated route.
    """
    return or_(
        ApnsDevice.session_id.is_(None),
        select(Session.id)
        .where(
            Session.id == ApnsDevice.session_id,
            Session.user_id == ApnsDevice.user_id,
            Session.is_active.is_(True),
            Session.expires_at > datetime.now(UTC),
        )
        .exists(),
    )


async def upsert(
    db: AsyncSession, *, user_id: uuid.UUID, token: str, session_id: uuid.UUID | None = None
) -> None:
    """Keep this iPhone's token for this person. An iPhone now signed in as
    somebody else becomes theirs."""
    await db.execute(
        insert(ApnsDevice)
        .values(id=uuid.uuid4(), token=token, user_id=user_id, session_id=session_id)
        .on_conflict_do_update(
            index_elements=[ApnsDevice.token],
            set_={"user_id": user_id, "session_id": session_id},
        )
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
        select(ApnsDevice)
        .where(ApnsDevice.user_id == user_id, _deliverable())
        .order_by(ApnsDevice.created_at)
    )
    return list(result.scalars().all())


async def subscribed(db: AsyncSession, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these people have at least one iPhone to push to."""
    if not user_ids:
        return set()
    result = await db.execute(
        select(ApnsDevice.user_id)
        .where(ApnsDevice.user_id.in_(user_ids), _deliverable())
        .distinct()
    )
    return set(result.scalars().all())


async def mark_sent(db: AsyncSession, device_id: uuid.UUID, at: datetime) -> None:
    await db.execute(update(ApnsDevice).where(ApnsDevice.id == device_id).values(last_sent_at=at))
    await db.flush()
