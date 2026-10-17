"""B53 — widget queue notify, round-robin, auto-assign."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.shop_widget_queue_notify import notify_widget_live_agent_queued

pytestmark = pytest.mark.anyio


async def test_notify_auto_assigns_widget_when_enabled() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    conv_id = uuid4()
    cs_id = uuid4()
    db = AsyncMock()

    with patch("app.services.shop_widget_queue_notify.settings") as settings:
        settings.SHOP_AI_NATIVE_WIDGET_QUEUE_NOTIFY_ENABLED = True
        with (
            patch(
                "app.services.shop_widget_queue_notify.resolve_round_robin_enabled",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.shop_widget_queue_notify.resolve_auto_assign_enabled",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.services.shop_widget_queue_notify.list_customer_care_user_ids",
                new=AsyncMock(return_value=[cs_id]),
            ),
            patch(
                "app.services.shop_widget_queue_notify.claim_widget_conversation",
                new=AsyncMock(),
            ) as claim,
            patch(
                "app.services.shop_widget_queue_notify.NotificationCenterService",
            ) as center_cls,
        ):
            write = AsyncMock()
            center_cls.return_value.write = write
            await notify_widget_live_agent_queued(
                db,
                organization_id=org_id,
                tenant_id=tenant_id,
                conversation_id=conv_id,
                customer_label="Khách A",
                preview="gặp nhân viên",
            )

    claim.assert_awaited_once()
    write.assert_awaited_once()
    assert write.await_args.kwargs["recipients"] == [cs_id]
