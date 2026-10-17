"""Internal Minerp tenant ↔ org lookup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.minerp_tenant_lookup import tenant_context_for_minerp_tenant

pytestmark = pytest.mark.anyio


async def test_tenant_context_for_minerp_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    org_id = uuid4()
    org = MagicMock()
    org.id = org_id
    org.minerp_tenant_id = tenant_id
    org.name = "Shop org"
    org.slug = "minerp-shop"
    org.is_personal = False

    monkeypatch.setattr(
        "app.services.minerp_tenant_lookup.organization_repo.get_by_minerp_tenant_id",
        AsyncMock(return_value=org),
    )
    db = MagicMock()
    ctx = await tenant_context_for_minerp_tenant(db, tenant_id)
    assert ctx.organization_id == org_id
    assert ctx.minerp_tenant_id == tenant_id
