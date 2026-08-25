"""ChannelIdentity repository (PostgreSQL async)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_identity import ChannelIdentity


async def get_by_id(db: AsyncSession, identity_id: UUID) -> ChannelIdentity | None:
    """Get a channel identity by ID."""
    return await db.get(ChannelIdentity, identity_id)


async def get_by_platform_user(
    db: AsyncSession,
    platform: str,
    platform_user_id: str,
) -> ChannelIdentity | None:
    """Get identity by platform + platform_user_id."""
    result = await db.execute(
        select(ChannelIdentity).where(
            ChannelIdentity.platform == platform,
            ChannelIdentity.platform_user_id == platform_user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_for_user(db: AsyncSession, *, user_id: UUID) -> list[ChannelIdentity]:
    """Every chat account this person has connected, oldest first.

    Ordered so the list does not reshuffle between visits: these rows are
    identical at a glance apart from the platform, and a list that reorders
    itself is one somebody unlinks the wrong row from.
    """
    result = await db.execute(
        select(ChannelIdentity)
        .where(ChannelIdentity.user_id == user_id)
        .order_by(ChannelIdentity.created_at)
    )
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    platform: str,
    platform_user_id: str,
    platform_username: str | None = None,
    platform_display_name: str | None = None,
    user_id: UUID | None = None,
) -> ChannelIdentity:
    """Create a new channel identity."""
    identity = ChannelIdentity(
        platform=platform,
        platform_user_id=platform_user_id,
        platform_username=platform_username,
        platform_display_name=platform_display_name,
        user_id=user_id,
    )
    db.add(identity)
    await db.flush()
    await db.refresh(identity)
    return identity


async def get_or_create(
    db: AsyncSession,
    *,
    platform: str,
    platform_user_id: str,
    platform_username: str | None = None,
    platform_display_name: str | None = None,
    user_id: UUID | None = None,
) -> ChannelIdentity:
    """The identity for this platform user, inserted once under contention.

    One person messaging two chats at once produces two webhooks whose sessions
    race here: both miss the `SELECT`, both `INSERT`, and the second violates
    `uq_channel_identity_platform_user` - the whole event fails and the user gets
    no reply (#17). The router's in-process lock does not help, because it is
    keyed on the chat, not on the identity, so the two webhooks hold different
    locks.

    The insert runs only on a miss, so an existing identity - every message after
    the first - is a plain read that writes nothing and holds no lock. That matters
    because the whole inbound message runs in one transaction, right through the
    agent's model call, and the identity is keyed per platform user rather than per
    chat: anything that wrote or locked the row here would hold it across the LLM
    call and serialise a user active in two chats at once.

    On the miss the insert closes the creation race with `ON CONFLICT DO NOTHING`
    and a re-`SELECT`. `DO NOTHING` waits on a concurrent *uncommitted* insert of
    the same key - it cannot decide whether to insert until that transaction ends -
    so by the time it returns the other row is committed, and the re-`SELECT`, a
    fresh statement under `READ COMMITTED`, reads it. The loser writes nothing and
    takes no row lock, so it does not hold one through its own run; `DO UPDATE`
    would, which is the difference on a first-message burst. The row is always
    present by the `SELECT` - inserted here, or committed by the winner this one
    lost to - so `scalar_one` cannot come up empty, and an existing `user_id`,
    username or display name is left untouched.
    """
    existing = await get_by_platform_user(db, platform, platform_user_id)
    if existing is not None:
        return existing

    insert_stmt = pg_insert(ChannelIdentity).values(
        platform=platform,
        platform_user_id=platform_user_id,
        platform_username=platform_username,
        platform_display_name=platform_display_name,
        user_id=user_id,
    )
    await db.execute(
        insert_stmt.on_conflict_do_nothing(index_elements=["platform", "platform_user_id"])
    )
    result = await db.execute(
        select(ChannelIdentity).where(
            ChannelIdentity.platform == platform,
            ChannelIdentity.platform_user_id == platform_user_id,
        )
    )
    return result.scalar_one()


async def update(
    db: AsyncSession,
    *,
    db_identity: ChannelIdentity,
    update_data: dict,
) -> ChannelIdentity:
    """Update a channel identity."""
    for field, value in update_data.items():
        setattr(db_identity, field, value)
    db.add(db_identity)
    await db.flush()
    await db.refresh(db_identity)
    return db_identity
