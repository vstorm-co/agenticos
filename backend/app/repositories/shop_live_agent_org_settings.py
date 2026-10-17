"""Org-scoped Shop live-agent settings."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.shop_live_agent_org_settings import ShopLiveAgentOrgSettings


async def get(db: AsyncSession, organization_id: UUID) -> ShopLiveAgentOrgSettings | None:
    return await db.get(ShopLiveAgentOrgSettings, organization_id)


async def get_or_create(db: AsyncSession, organization_id: UUID) -> ShopLiveAgentOrgSettings:
    row = await get(db, organization_id)
    if row is not None:
        return row
    row = ShopLiveAgentOrgSettings(organization_id=organization_id)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def set_round_robin_enabled(
    db: AsyncSession,
    organization_id: UUID,
    *,
    enabled: bool | None,
) -> ShopLiveAgentOrgSettings:
    row = await get_or_create(db, organization_id)
    row.live_agent_round_robin_enabled = enabled
    await db.flush()
    await db.refresh(row)
    return row


async def set_auto_assign_enabled(
    db: AsyncSession,
    organization_id: UUID,
    *,
    enabled: bool | None,
) -> ShopLiveAgentOrgSettings:
    row = await get_or_create(db, organization_id)
    row.live_agent_auto_assign_enabled = enabled
    await db.flush()
    await db.refresh(row)
    return row


async def set_idle_release_minutes(
    db: AsyncSession,
    organization_id: UUID,
    *,
    minutes: int | None,
) -> ShopLiveAgentOrgSettings:
    row = await get_or_create(db, organization_id)
    if minutes is None:
        row.live_agent_idle_release_minutes = None
    else:
        row.live_agent_idle_release_minutes = max(0, min(int(minutes), 1440))
    await db.flush()
    await db.refresh(row)
    return row
