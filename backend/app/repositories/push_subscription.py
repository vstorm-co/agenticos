"""Data access for Web Push subscriptions (PostgreSQL async)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.apns_device import ApnsDevice
from app.db.models.push_subscription import PushSubscription
from app.db.models.session import Session


def _deliverable() -> ColumnElement[bool]:
    """Linked devices stop receiving push when their sign-in ends.

    Existing subscriptions without a recorded session retain their standing
    permission; new registrations are linked by the authenticated route.
    """
    return or_(
        PushSubscription.session_id.is_(None),
        select(Session.id)
        .where(
            Session.id == PushSubscription.session_id,
            Session.user_id == PushSubscription.user_id,
            Session.is_active.is_(True),
            Session.expires_at > datetime.now(UTC),
        )
        .exists(),
    )


async def upsert(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
    session_id: uuid.UUID | None = None,
) -> None:
    """Keep this browser's subscription for this person.

    On the endpoint, which is the browser: subscribing again refreshes its
    keys, and a browser now signed in as somebody else becomes theirs - the
    previous person stops receiving pushes in a browser they no longer use.
    """
    values = {
        "p256dh": p256dh,
        "auth": auth,
        "user_agent": user_agent,
        "user_id": user_id,
        "session_id": session_id,
    }
    await db.execute(
        insert(PushSubscription)
        .values(id=uuid.uuid4(), endpoint=endpoint, **values)
        .on_conflict_do_update(index_elements=[PushSubscription.endpoint], set_=values)
    )
    await db.flush()


async def delete_for_user(db: AsyncSession, *, user_id: uuid.UUID, endpoint: str) -> bool:
    """Forget one of this person's browsers. Whether there was one to forget."""
    result = await db.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint
        )
    )
    await db.flush()
    return bool(getattr(result, "rowcount", 0))


async def delete_by_id(db: AsyncSession, subscription_id: uuid.UUID) -> None:
    await db.execute(delete(PushSubscription).where(PushSubscription.id == subscription_id))
    await db.flush()


async def list_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[PushSubscription]:
    result = await db.execute(
        select(PushSubscription)
        .where(PushSubscription.user_id == user_id, _deliverable())
        .order_by(PushSubscription.created_at)
    )
    return list(result.scalars().all())


async def subscribed(db: AsyncSession, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these people have at least one browser to push to."""
    if not user_ids:
        return set()
    result = await db.execute(
        select(PushSubscription.user_id)
        .where(PushSubscription.user_id.in_(user_ids), _deliverable())
        .distinct()
    )
    return set(result.scalars().all())


async def mark_sent(db: AsyncSession, subscription_id: uuid.UUID, at: datetime) -> None:
    await db.execute(
        update(PushSubscription)
        .where(PushSubscription.id == subscription_id)
        .values(last_sent_at=at)
    )
    await db.flush()


async def sessions_with_push(db: AsyncSession, session_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these sign-ins registered a browser or a phone for push."""
    if not session_ids:
        return set()
    web = await db.execute(
        select(PushSubscription.session_id).where(PushSubscription.session_id.in_(session_ids))
    )
    phones = await db.execute(
        select(ApnsDevice.session_id).where(ApnsDevice.session_id.in_(session_ids))
    )
    return {sid for sid in [*web.scalars(), *phones.scalars()] if sid is not None}
