"""Data access for the codes that connect a chat account to a person."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_link_code import ChannelLinkCode


async def create(
    db: AsyncSession, *, user_id: UUID, code: str, expires_at: datetime
) -> ChannelLinkCode:
    """Store one outstanding code for a user."""
    link_code = ChannelLinkCode(user_id=user_id, code=code, expires_at=expires_at)
    db.add(link_code)
    await db.flush()
    await db.refresh(link_code)
    return link_code


async def get_valid(db: AsyncSession, *, code: str, now: datetime) -> ChannelLinkCode | None:
    """The unexpired code, or None.

    Expiry is part of the lookup rather than a check the caller remembers: a
    bearer credential whose freshness is somebody else's responsibility is one
    that eventually gets read without it.
    """
    result = await db.execute(
        select(ChannelLinkCode).where(
            ChannelLinkCode.code == code,
            ChannelLinkCode.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def delete_for_user(db: AsyncSession, *, user_id: UUID) -> None:
    """Drop every outstanding code for a user.

    Called before minting one and again once a code is spent, which is what makes
    a code single-use and makes "one at a time" true: a person who asks twice
    because the first code scrolled away must not leave the first one usable.
    """
    await db.execute(delete(ChannelLinkCode).where(ChannelLinkCode.user_id == user_id))
    await db.flush()
