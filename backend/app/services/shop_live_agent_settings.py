"""Shop live-agent org settings + env defaults (D3 B53)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories import shop_live_agent_org_settings as settings_repo
from app.schemas.shop_live_agent_settings import (
    ShopLiveAgentSettingsPatch,
    ShopLiveAgentSettingsRead,
)


async def resolve_idle_release_minutes(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> int:
    row = await settings_repo.get(db, organization_id)
    if row is not None and row.live_agent_idle_release_minutes is not None:
        return max(0, int(row.live_agent_idle_release_minutes))
    return max(0, int(settings.SHOP_LIVE_AGENT_IDLE_RELEASE_MINUTES))


async def resolve_round_robin_enabled(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> bool:
    row = await settings_repo.get(db, organization_id)
    if row is not None and row.live_agent_round_robin_enabled is not None:
        return bool(row.live_agent_round_robin_enabled)
    return bool(settings.SHOP_LIVE_AGENT_ROUND_ROBIN_ENABLED)


async def resolve_auto_assign_enabled(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> bool:
    row = await settings_repo.get(db, organization_id)
    if row is not None and row.live_agent_auto_assign_enabled is not None:
        return bool(row.live_agent_auto_assign_enabled)
    return bool(settings.SHOP_LIVE_AGENT_AUTO_ASSIGN_ENABLED)


class ShopLiveAgentSettingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_settings(self, *, organization_id: UUID) -> ShopLiveAgentSettingsRead:
        row = await settings_repo.get(self.db, organization_id)
        tenant_idle = row.live_agent_idle_release_minutes if row is not None else None
        tenant_rr = row.live_agent_round_robin_enabled if row is not None else None
        tenant_aa = row.live_agent_auto_assign_enabled if row is not None else None
        platform_idle = max(0, int(settings.SHOP_LIVE_AGENT_IDLE_RELEASE_MINUTES))
        platform_rr = bool(settings.SHOP_LIVE_AGENT_ROUND_ROBIN_ENABLED)
        platform_aa = bool(settings.SHOP_LIVE_AGENT_AUTO_ASSIGN_ENABLED)
        return ShopLiveAgentSettingsRead(
            idle_release_minutes=tenant_idle,
            idle_release_minutes_effective=await resolve_idle_release_minutes(
                self.db, organization_id=organization_id
            ),
            platform_default_minutes=platform_idle,
            round_robin_enabled=tenant_rr,
            round_robin_enabled_effective=await resolve_round_robin_enabled(
                self.db, organization_id=organization_id
            ),
            auto_assign_enabled=tenant_aa,
            auto_assign_enabled_effective=await resolve_auto_assign_enabled(
                self.db, organization_id=organization_id
            ),
            platform_default_round_robin=platform_rr,
            platform_default_auto_assign=platform_aa,
        )

    async def patch_settings(
        self,
        *,
        organization_id: UUID,
        data: ShopLiveAgentSettingsPatch,
    ) -> ShopLiveAgentSettingsRead:
        if "idle_release_minutes" in data.model_fields_set:
            await settings_repo.set_idle_release_minutes(
                self.db,
                organization_id,
                minutes=data.idle_release_minutes,
            )
        if "round_robin_enabled" in data.model_fields_set:
            await settings_repo.set_round_robin_enabled(
                self.db,
                organization_id,
                enabled=data.round_robin_enabled,
            )
        if "auto_assign_enabled" in data.model_fields_set:
            await settings_repo.set_auto_assign_enabled(
                self.db,
                organization_id,
                enabled=data.auto_assign_enabled,
            )
        return await self.get_settings(organization_id=organization_id)
