"""B71 — channel queue notify on Zalo/Messenger handoff."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.config import settings
from app.services.shop_widget_queue_notify import notify_channel_live_agent_queued

pytestmark = pytest.mark.anyio


async def test_channel_notify_writes_notification() -> None:
    db = MagicMock()
    org_id = uuid4()
    tenant_id = uuid4()
    session_id = uuid4()

    with (
        patch.object(settings, "SHOP_AI_NATIVE_CHANNEL_QUEUE_NOTIFY_ENABLED", True),
        patch(
            "app.services.shop_widget_queue_notify.resolve_round_robin_enabled",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.shop_widget_queue_notify.resolve_auto_assign_enabled",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.shop_widget_queue_notify.list_customer_care_user_ids",
            new=AsyncMock(return_value=[uuid4()]),
        ),
        patch(
            "app.services.shop_widget_queue_notify.NotificationCenterService"
        ) as ncs_cls,
    ):
        write = AsyncMock()
        ncs_cls.return_value.write = write
        await notify_channel_live_agent_queued(
            db,
            organization_id=org_id,
            tenant_id=tenant_id,
            session_id=session_id,
            channel="zalo",
            customer_label="Zalo #123456",
            preview="gap nhan vien",
        )

    write.assert_awaited_once()
    kwargs = write.await_args.kwargs
    assert kwargs["occurrence_id"] == f"shop-channel-queue:{session_id}"
    assert kwargs["render_context"]["channel"] == "zalo"
