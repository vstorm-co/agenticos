"""B70 — shop AI entitlement hook (CDC deferred)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services.shop_ai_entitlement import require_shop_ai_entitlement

pytestmark = pytest.mark.anyio


async def test_entitlement_noop_when_disabled() -> None:
    tenant_id = uuid4()
    with patch(
        "app.services.shop_ai_entitlement.settings.SHOP_AI_NATIVE_ENTITLEMENT_CHECK_ENABLED",
        False,
    ):
        await require_shop_ai_entitlement(MagicMock(), minerp_tenant_id=tenant_id)
