"""Shop CSKH channel sessions — scoped via shop channel bots (D3 B67)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_bot import BOT_KIND_SHOP_CSKH, ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_session import ChannelSession
from app.services.shop_channel_handling import HANDLING_MODE_AI, HANDLING_MODE_HUMAN


def _shop_bot_scope(
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
) -> tuple:
    return (
        ChannelBot.organization_id == organization_id,
        ChannelBot.minerp_tenant_id == minerp_tenant_id,
        ChannelBot.bot_kind == BOT_KIND_SHOP_CSKH,
    )


async def get_by_id_for_shop(
    db: AsyncSession,
    session_id: UUID,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
) -> ChannelSession | None:
    result = await db.execute(
        select(ChannelSession)
        .join(ChannelBot, ChannelSession.bot_id == ChannelBot.id)
        .where(
            ChannelSession.id == session_id,
            *_shop_bot_scope(
                organization_id=organization_id,
                minerp_tenant_id=minerp_tenant_id,
            ),
        )
    )
    return result.scalar_one_or_none()


async def list_for_shop(
    db: AsyncSession,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
    platform: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[tuple[ChannelSession, ChannelBot, ChannelIdentity]]:
    query = (
        select(ChannelSession, ChannelBot, ChannelIdentity)
        .join(ChannelBot, ChannelSession.bot_id == ChannelBot.id)
        .join(ChannelIdentity, ChannelSession.identity_id == ChannelIdentity.id)
        .where(
            *_shop_bot_scope(
                organization_id=organization_id,
                minerp_tenant_id=minerp_tenant_id,
            )
        )
    )
    if platform:
        query = query.where(ChannelBot.platform == platform)
    query = (
        query.order_by(
            func.coalesce(ChannelSession.last_message_at, ChannelSession.created_at).desc()
        )
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.all())


async def count_for_shop(
    db: AsyncSession,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
    platform: str | None = None,
) -> int:
    query = (
        select(func.count())
        .select_from(ChannelSession)
        .join(ChannelBot, ChannelSession.bot_id == ChannelBot.id)
        .where(
            *_shop_bot_scope(
                organization_id=organization_id,
                minerp_tenant_id=minerp_tenant_id,
            )
        )
    )
    if platform:
        query = query.where(ChannelBot.platform == platform)
    result = await db.scalar(query)
    return int(result or 0)


async def count_by_handling_mode_for_shop(
    db: AsyncSession,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
    handling_mode: str,
    platform: str | None = None,
) -> int:
    query = (
        select(func.count())
        .select_from(ChannelSession)
        .join(ChannelBot, ChannelSession.bot_id == ChannelBot.id)
        .where(
            *_shop_bot_scope(
                organization_id=organization_id,
                minerp_tenant_id=minerp_tenant_id,
            ),
            ChannelSession.handling_mode == handling_mode,
        )
    )
    if platform:
        query = query.where(ChannelBot.platform == platform)
    result = await db.scalar(query)
    return int(result or 0)


async def release_idle_human_sessions_for_shop(
    db: AsyncSession,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
    idle_before: datetime,
) -> int:
    result = await db.execute(
        select(ChannelSession)
        .join(ChannelBot, ChannelSession.bot_id == ChannelBot.id)
        .where(
            *_shop_bot_scope(
                organization_id=organization_id,
                minerp_tenant_id=minerp_tenant_id,
            ),
            ChannelSession.handling_mode == HANDLING_MODE_HUMAN,
            ChannelSession.claimed_at.is_not(None),
            func.coalesce(ChannelSession.last_message_at, ChannelSession.claimed_at)
            < idle_before,
        )
    )
    rows = list(result.scalars().all())
    now = datetime.now(UTC)
    for session in rows:
        session.handling_mode = HANDLING_MODE_AI
        session.claimed_by_user_id = None
        session.claimed_by_name = None
        session.claimed_at = None
        session.updated_at = now
        db.add(session)
    if rows:
        await db.flush()
    return len(rows)
