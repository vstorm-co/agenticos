"""Data access for chat accounts waiting to be claimed by a person."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_link_request import ChannelLinkRequest


async def create(
    db: AsyncSession,
    *,
    token: str,
    platform: str,
    platform_user_id: str,
    platform_username: str | None,
    platform_display_name: str | None,
    expires_at: datetime,
) -> ChannelLinkRequest:
    """Store one outstanding request for a chat account."""
    request = ChannelLinkRequest(
        token=token,
        platform=platform,
        platform_user_id=platform_user_id,
        platform_username=platform_username,
        platform_display_name=platform_display_name,
        expires_at=expires_at,
    )
    db.add(request)
    await db.flush()
    await db.refresh(request)
    return request


async def get_valid(db: AsyncSession, *, token: str, now: datetime) -> ChannelLinkRequest | None:
    """The unexpired request, or None.

    Expiry is part of the lookup rather than a check the caller remembers: a
    bearer credential whose freshness is somebody else's responsibility is one
    that eventually gets read without it.
    """
    result = await db.execute(
        select(ChannelLinkRequest).where(
            ChannelLinkRequest.token == token,
            ChannelLinkRequest.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def delete_for_identity(db: AsyncSession, *, platform: str, platform_user_id: str) -> None:
    """Drop every outstanding request for one chat account.

    Called before minting one and again once a request is spent. That is what
    makes a link single-use, and what keeps the unique constraint true without
    an upsert: somebody who asks twice must not leave the first URL live.
    """
    await db.execute(
        delete(ChannelLinkRequest).where(
            ChannelLinkRequest.platform == platform,
            ChannelLinkRequest.platform_user_id == platform_user_id,
        )
    )
    await db.flush()


async def delete_by_id(db: AsyncSession, request_id: UUID) -> None:
    """Drop one request by id, once it has been confirmed."""
    await db.execute(delete(ChannelLinkRequest).where(ChannelLinkRequest.id == request_id))
    await db.flush()
