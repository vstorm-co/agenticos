"""B59 — Shop KB document list/upload org guard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.services.shop_tenant_knowledge import require_kb_for_shop_organization

pytestmark = pytest.mark.anyio


async def test_require_kb_rejects_other_org() -> None:
    org_id = uuid4()
    kb_id = uuid4()
    kb = MagicMock(organization_id=uuid4())

    db = AsyncMock()
    with patch(
        "app.services.shop_tenant_knowledge.knowledge_base_repo.get_by_id",
        new=AsyncMock(return_value=kb),
    ):
        with pytest.raises(NotFoundError, match="Knowledge base not found"):
            await require_kb_for_shop_organization(
                db,
                organization_id=org_id,
                kb_id=kb_id,
            )


async def test_require_kb_returns_row_for_org() -> None:
    org_id = uuid4()
    kb_id = uuid4()
    kb = MagicMock(id=kb_id, organization_id=org_id)

    db = AsyncMock()
    with patch(
        "app.services.shop_tenant_knowledge.knowledge_base_repo.get_by_id",
        new=AsyncMock(return_value=kb),
    ):
        result = await require_kb_for_shop_organization(
            db,
            organization_id=org_id,
            kb_id=kb_id,
        )

    assert result is kb
