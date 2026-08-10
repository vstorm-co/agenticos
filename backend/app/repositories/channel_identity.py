"""ChannelIdentity repository (PostgreSQL async)."""

from uuid import UUID

from sqlalchemy import select
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
