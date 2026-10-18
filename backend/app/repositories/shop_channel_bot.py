"""Shop CSKH channel bots — org + minerp tenant scope (D3 B65)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_bot import BOT_KIND_SHOP_CSKH, ChannelBot


async def get_for_shop(
    db: AsyncSession,
    *,
    bot_id: UUID,
    organization_id: UUID,
    minerp_tenant_id: UUID,
) -> ChannelBot | None:
    result = await db.execute(
        select(ChannelBot).where(
            ChannelBot.id == bot_id,
            ChannelBot.organization_id == organization_id,
            ChannelBot.minerp_tenant_id == minerp_tenant_id,
            ChannelBot.bot_kind == BOT_KIND_SHOP_CSKH,
        )
    )
    return result.scalar_one_or_none()


async def list_for_shop(
    db: AsyncSession,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
    skip: int = 0,
    limit: int = 50,
) -> list[ChannelBot]:
    result = await db.execute(
        select(ChannelBot)
        .where(
            ChannelBot.organization_id == organization_id,
            ChannelBot.minerp_tenant_id == minerp_tenant_id,
            ChannelBot.bot_kind == BOT_KIND_SHOP_CSKH,
        )
        .order_by(ChannelBot.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_for_shop(
    db: AsyncSession,
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
) -> int:
    result = await db.scalar(
        select(func.count())
        .select_from(ChannelBot)
        .where(
            ChannelBot.organization_id == organization_id,
            ChannelBot.minerp_tenant_id == minerp_tenant_id,
            ChannelBot.bot_kind == BOT_KIND_SHOP_CSKH,
        )
    )
    return result or 0
