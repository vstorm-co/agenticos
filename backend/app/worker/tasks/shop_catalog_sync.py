"""Background catalog item sync (D3 B63) and nightly beat (B74)."""

from __future__ import annotations

import logging
from uuid import UUID

from prefect import flow

from app.db.session import get_worker_db_context
from app.services.shop_catalog_sync import (
    ShopCatalogSyncService,
    run_nightly_catalog_sync_all_entitled,
)

logger = logging.getLogger(__name__)


async def run_catalog_item_sync_background(
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
    item_id: UUID,
    action: str,
) -> None:
    async with get_worker_db_context() as db:
        out = await ShopCatalogSyncService(db).sync_item_by_id(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            item_id=item_id,
            action=action,
        )
    logger.info(
        "Catalog item sync item=%s tenant=%s status=%s message=%s",
        item_id,
        minerp_tenant_id,
        out.status,
        out.message,
    )


@flow(name="shop-catalog-sync-nightly")
async def shop_catalog_sync_nightly_flow() -> dict[str, int]:
    async with get_worker_db_context() as db:
        try:
            return await run_nightly_catalog_sync_all_entitled(db)
        except Exception:
            logger.exception("Shop catalog nightly sync flow failed")
            raise
