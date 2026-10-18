"""B55 — live-agent inbox summary native."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.shop_live_agent_inbox import ShopLiveAgentInboxService

pytestmark = pytest.mark.anyio


async def test_inbox_summary_counts_widget_queued() -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    db = AsyncMock()
    with (
        patch(
            "app.services.shop_live_agent_inbox.release_idle_human_sessions",
            new=AsyncMock(),
        ),
        patch(
            "app.services.shop_live_agent_inbox.widget_handling_repo.count_by_handling_mode_for_organization",
            new=AsyncMock(return_value=3),
        ),
        patch(
            "app.services.shop_live_agent_inbox.shop_channel_session_repo.count_by_handling_mode_for_shop",
            new=AsyncMock(return_value=0),
        ),
    ):
        summary = await ShopLiveAgentInboxService(db).build_summary(
            organization_id=org_id,
            tenant_id=tenant_id,
        )
    assert summary.queued_widget_count == 3
    assert summary.queued_zalo_count == 0
    assert summary.queued_messenger_count == 0
    assert summary.queued_total == 3
