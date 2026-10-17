"""B50 — widget Studio routes on Agentra."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.anyio


async def test_widget_claim_route(client, api_key_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.schemas.shop_widget_conversation import ShopWidgetConversationRead
    from datetime import UTC, datetime

    tenant_id = uuid4()
    conv_id = uuid4()
    org_id = uuid4()
    org = type("Org", (), {"id": org_id})()

    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.require_org_for_shop_tenant",
        AsyncMock(return_value=org),
    )
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.claim_widget_conversation",
        AsyncMock(),
    )
    read = ShopWidgetConversationRead(
        id=conv_id,
        customer_ref="ABCD1234",
        created_at=datetime.now(UTC),
        handling_mode="human",
        claimed_by_name="Staff",
    )
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.ShopWidgetConversationService",
        lambda db: type(
            "Svc",
            (),
            {
                "get_conversation_read": AsyncMock(return_value=read),
            },
        )(),
    )

    headers = {**api_key_headers, "X-Tenant-Id": str(tenant_id)}
    resp = await client.post(
        f"/api/v1/internal/shop-ai/widget/conversations/{conv_id}/claim",
        headers=headers,
        json={"claimed_by_user_id": str(uuid4()), "claimed_by_name": "Staff"},
    )
    assert resp.status_code == 200
    assert resp.json()["handling_mode"] == "human"
