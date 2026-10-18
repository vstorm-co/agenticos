"""Shop catalog sync settings repository (D3 B63)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.shop_catalog_sync_settings import ShopCatalogSyncSettings


async def get(db: AsyncSession, minerp_tenant_id: UUID) -> ShopCatalogSyncSettings | None:
    return await db.get(ShopCatalogSyncSettings, minerp_tenant_id)


async def get_or_create(
    db: AsyncSession,
    *,
    minerp_tenant_id: UUID,
    organization_id: UUID,
) -> ShopCatalogSyncSettings:
    row = await get(db, minerp_tenant_id)
    if row is not None:
        return row
    now = datetime.now(UTC)
    row = ShopCatalogSyncSettings(
        minerp_tenant_id=minerp_tenant_id,
        organization_id=organization_id,
        enabled=False,
        last_item_count=0,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def set_enabled(
    db: AsyncSession,
    *,
    minerp_tenant_id: UUID,
    organization_id: UUID,
    enabled: bool,
) -> ShopCatalogSyncSettings:
    row = await get_or_create(
        db, minerp_tenant_id=minerp_tenant_id, organization_id=organization_id
    )
    row.enabled = enabled
    await db.flush()
    await db.refresh(row)
    return row


async def record_run(
    db: AsyncSession,
    minerp_tenant_id: UUID,
    *,
    success: bool,
    item_count: int,
    error: str | None = None,
    manual: bool = False,
    run_at: datetime | None = None,
) -> ShopCatalogSyncSettings:
    row = await get(db, minerp_tenant_id)
    if row is None:
        raise ValueError("catalog sync settings missing")
    now = run_at or datetime.now(UTC)
    row.last_run_at = now
    row.last_item_count = item_count
    row.last_error = error
    if success:
        row.last_success_at = now
    if manual:
        row.last_manual_run_at = now
    await db.flush()
    await db.refresh(row)
    return row


async def list_enabled_settings(db: AsyncSession) -> list[ShopCatalogSyncSettings]:
    result = await db.execute(
        select(ShopCatalogSyncSettings).where(ShopCatalogSyncSettings.enabled.is_(True))
    )
    return list(result.scalars().all())
