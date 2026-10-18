"""B67 — shop channel session inbox helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError
from app.services.shop_channel_conversation import (
    ShopChannelConversationService,
    _customer_label,
    _message_sender_type,
)

pytestmark = pytest.mark.anyio


def test_customer_label_zalo() -> None:
    assert _customer_label(None, "1234567890", platform="zalo") == "Zalo #567890"


def test_message_sender_type_staff() -> None:
    assert _message_sender_type("assistant", "staff") == "staff"
    assert _message_sender_type("assistant", "gpt-4") == "bot"


async def test_reply_requires_human_mode() -> None:
    db = MagicMock()
    org_id = uuid4()
    tenant_id = uuid4()
    session_id = uuid4()

    session = MagicMock()
    session.conversation_id = uuid4()
    session.handling_mode = "ai"
    bot = MagicMock()

    with patch.object(
        ShopChannelConversationService,
        "_require_session",
        AsyncMock(return_value=(session, bot)),
    ):
        with pytest.raises(BadRequestError, match="Claim the session"):
            await ShopChannelConversationService(db).reply_session(
                organization_id=org_id,
                minerp_tenant_id=tenant_id,
                session_id=session_id,
                text="Hello",
            )


async def test_list_sessions_empty() -> None:
    db = MagicMock()
    org_id = uuid4()
    tenant_id = uuid4()

    with (
        patch(
            "app.services.shop_live_agent_inbox.release_idle_human_sessions",
            AsyncMock(),
        ),
        patch(
            "app.services.shop_channel_conversation.shop_session_repo.list_for_shop",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.shop_channel_conversation.shop_session_repo.count_for_shop",
            AsyncMock(return_value=0),
        ),
    ):
        out = await ShopChannelConversationService(db).list_sessions(
            organization_id=org_id,
            minerp_tenant_id=tenant_id,
            platform="zalo",
        )

    assert out.total == 0
    assert out.items == []
