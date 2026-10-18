"""B63 — shop catalog sync native."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.shop_catalog_sync import ShopCatalogSyncService

pytestmark = pytest.mark.anyio


async def test_run_indexes_new_catalog_items() -> None:
    db = MagicMock()
    org_id = uuid4()
    tenant_id = uuid4()
    kb_id = uuid4()
    kb = MagicMock(id=kb_id, collection_name="shop-catalog", vector_tenant="t1")
    settings = MagicMock(
        enabled=True,
        last_manual_run_at=None,
    )

    item = {"id": str(uuid4()), "name": "SP A", "lifecycle_status_code": "ACTIVE"}

    with (
        patch(
            "app.services.shop_catalog_sync.settings_repo.get_or_create",
            new=AsyncMock(return_value=settings),
        ),
        patch(
            "app.services.shop_catalog_sync.ensure_shop_catalog_kb",
            new=AsyncMock(return_value=kb),
        ),
        patch(
            "app.services.shop_catalog_sync.shop_bff.list_catalog_items",
            new=AsyncMock(
                return_value={"items": [item], "has_more": False, "next_cursor": 0},
            ),
        ),
        patch.object(
            ShopCatalogSyncService,
            "_sync_item",
            new=AsyncMock(return_value="indexed"),
        ) as sync_item,
        patch(
            "app.services.shop_catalog_sync.settings_repo.record_run",
            new=AsyncMock(),
        ),
        patch.object(ShopCatalogSyncService, "_tombstone_missing", new=AsyncMock(return_value=0)),
    ):
        out = await ShopCatalogSyncService(db).run(
            organization_id=org_id,
            minerp_tenant_id=tenant_id,
            manual=True,
        )

    assert out.status == "done"
    assert out.indexed == 1
    sync_item.assert_awaited_once()


async def test_sync_item_skipped_when_disabled() -> None:
    db = MagicMock()
    settings = MagicMock(enabled=False)
    item_id = uuid4()

    with patch(
        "app.services.shop_catalog_sync.settings_repo.get_or_create",
        new=AsyncMock(return_value=settings),
    ):
        out = await ShopCatalogSyncService(db).sync_item_by_id(
            organization_id=uuid4(),
            minerp_tenant_id=uuid4(),
            item_id=item_id,
        )

    assert out.status == "skipped"
