"""B73 — shop AI entitlement via IAM CDC replica."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError
from app.services.shop_ai_entitlement import require_shop_ai_entitlement

pytestmark = pytest.mark.anyio


async def test_entitlement_denied_when_enabled_and_no_row() -> None:
    tenant_id = uuid4()
    db = MagicMock()
    with (
        patch(
            "app.services.shop_ai_entitlement.settings.SHOP_AI_NATIVE_ENTITLEMENT_CHECK_ENABLED",
            True,
        ),
        patch(
            "app.services.shop_ai_entitlement.tenant_has_service",
            AsyncMock(return_value=False),
        ),
    ):
        with pytest.raises(AuthorizationError):
            await require_shop_ai_entitlement(db, minerp_tenant_id=tenant_id)


async def test_entitlement_passes_when_enabled_and_row_present() -> None:
    tenant_id = uuid4()
    db = MagicMock()
    with (
        patch(
            "app.services.shop_ai_entitlement.settings.SHOP_AI_NATIVE_ENTITLEMENT_CHECK_ENABLED",
            True,
        ),
        patch(
            "app.services.shop_ai_entitlement.tenant_has_service",
            AsyncMock(return_value=True),
        ),
    ):
        await require_shop_ai_entitlement(db, minerp_tenant_id=tenant_id)
