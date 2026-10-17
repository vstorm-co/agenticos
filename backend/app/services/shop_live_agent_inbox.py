"""Live-agent inbox summary + idle release (D3 B54/B55)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import organization as organization_repo
from app.repositories import shop_widget_handling as widget_handling_repo
from app.schemas.shop_live_agent_inbox import ShopLiveAgentInboxSummaryRead
from app.services.shop_channel_handling import HANDLING_MODE_QUEUED
from app.services.shop_live_agent_settings import resolve_idle_release_minutes
from app.services.shop_widget_idle_release import release_idle_widget_sessions_for_organization


async def release_idle_human_sessions(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
) -> None:
    idle_minutes = await resolve_idle_release_minutes(db, organization_id=organization_id)
    if idle_minutes <= 0:
        return
    idle_before = datetime.now(UTC) - timedelta(minutes=idle_minutes)
    await release_idle_widget_sessions_for_organization(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        idle_before=idle_before,
    )


async def release_idle_human_sessions_all_shop_orgs(db: AsyncSession) -> dict[str, int]:
    released_orgs = 0
    skipped_orgs = 0
    widget_rows_released = 0
    for org in await organization_repo.list_with_minerp_tenant_id(db):
        assert org.minerp_tenant_id is not None
        idle_minutes = await resolve_idle_release_minutes(db, organization_id=org.id)
        if idle_minutes <= 0:
            skipped_orgs += 1
            continue
        idle_before = datetime.now(UTC) - timedelta(minutes=idle_minutes)
        widget_rows_released += await release_idle_widget_sessions_for_organization(
            db,
            organization_id=org.id,
            tenant_id=org.minerp_tenant_id,
            idle_before=idle_before,
        )
        released_orgs += 1
    return {
        "released_orgs": released_orgs,
        "skipped_orgs": skipped_orgs,
        "widget_sessions_released": widget_rows_released,
    }


class ShopLiveAgentInboxService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build_summary(
        self,
        *,
        organization_id: UUID,
        tenant_id: UUID,
    ) -> ShopLiveAgentInboxSummaryRead:
        await release_idle_human_sessions(
            self.db,
            organization_id=organization_id,
            tenant_id=tenant_id,
        )
        widget = await widget_handling_repo.count_by_handling_mode_for_organization(
            self.db,
            organization_id,
            handling_mode=HANDLING_MODE_QUEUED,
        )
        # Channel live-agent OLTP not on Agentra yet — counts stay 0 until D3 channel slice.
        zalo = 0
        messenger = 0
        return ShopLiveAgentInboxSummaryRead(
            queued_widget_count=widget,
            queued_zalo_count=zalo,
            queued_messenger_count=messenger,
            queued_total=widget + zalo + messenger,
        )
