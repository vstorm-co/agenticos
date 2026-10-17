"""B52 — widget thread message search."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.shop_widget_conversation_service import ShopWidgetConversationService
from app.services.shop_widget_customer import WIDGET_CONVERSATION_TITLE

pytestmark = pytest.mark.anyio


async def test_search_widget_messages_across_session_threads() -> None:
    organization_id = uuid4()
    tenant_id = uuid4()
    conversation_id = uuid4()
    session_id = uuid4()
    now = datetime.now(UTC)
    conv = MagicMock(
        organization_id=organization_id,
        user_id=None,
        title=f"{WIDGET_CONVERSATION_TITLE}|{session_id}",
    )
    hit = MagicMock(
        id=uuid4(),
        role="user",
        content="giao hàng bao lâu",
        model_name=None,
        created_at=now,
    )
    db = AsyncMock()

    with (
        patch(
            "app.services.shop_widget_conversation_service.conversation_repo.get_conversation_by_id",
            new=AsyncMock(return_value=conv),
        ),
        patch(
            "app.services.shop_widget_conversation_service.widget_conv_repo.list_conversation_ids_for_widget_session",
            new=AsyncMock(return_value=[conversation_id]),
        ),
        patch(
            "app.services.shop_widget_conversation_service.widget_conv_repo.search_messages_in_conversations",
            new=AsyncMock(return_value=([hit], 1)),
        ) as search,
    ):
        result = await ShopWidgetConversationService(db).search_messages(
            organization_id=organization_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            query="giao",
        )

    search.assert_awaited_once()
    assert result.total == 1
    assert result.items[0].content == "giao hàng bao lâu"
    assert result.items[0].sender_type == "customer"
