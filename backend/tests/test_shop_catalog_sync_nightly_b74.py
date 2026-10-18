"""B74 — nightly catalog sync beat."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.shop_catalog_sync import run_nightly_catalog_sync_all_entitled

pytestmark = pytest.mark.anyio


async def test_nightly_skips_when_no_entitled_tenants() -> None:
    db = MagicMock()
    tenant_id = uuid4()
    org_id = uuid4()
    row = MagicMock(minerp_tenant_id=tenant_id, organization_id=org_id)

    with (
        patch(
            "app.repositories.tenant_service_entitlement.list_tenants_with_service",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.shop_catalog_sync.settings_repo.list_enabled_settings",
            new=AsyncMock(return_value=[row]),
        ),
    ):
        out = await run_nightly_catalog_sync_all_entitled(db)

    assert out == {"synced": 0, "skipped": 1, "failed": 0}


async def test_nightly_runs_for_entitled_enabled_tenant() -> None:
    db = MagicMock()
    tenant_id = uuid4()
    org_id = uuid4()
    row = MagicMock(minerp_tenant_id=tenant_id, organization_id=org_id)
    run_out = MagicMock(status="done")

    with (
        patch(
            "app.repositories.tenant_service_entitlement.list_tenants_with_service",
            new=AsyncMock(return_value=[tenant_id]),
        ),
        patch(
            "app.services.shop_catalog_sync.settings_repo.list_enabled_settings",
            new=AsyncMock(return_value=[row]),
        ),
        patch(
            "app.services.shop_catalog_sync.ShopCatalogSyncService.run",
            new=AsyncMock(return_value=run_out),
        ) as run_sync,
    ):
        out = await run_nightly_catalog_sync_all_entitled(db)

    assert out == {"synced": 1, "skipped": 0, "failed": 0}
    run_sync.assert_awaited_once_with(
        organization_id=org_id,
        minerp_tenant_id=tenant_id,
        manual=False,
    )
