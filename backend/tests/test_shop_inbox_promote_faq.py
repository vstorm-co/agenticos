"""B56 — promote widget message to FAQ suggestion."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError
from app.services.shop_widget_conversation_service import ShopWidgetConversationService
from app.services.shop_widget_customer import widget_conversation_title

pytestmark = pytest.mark.anyio


async def test_promote_user_message_creates_suggestion() -> None:
    tenant_id = uuid4()
    org_id = uuid4()
    conversation_id = uuid4()
    message_id = uuid4()
    kb_id = uuid4()
    session_id = uuid4()

    conv = MagicMock(
        organization_id=org_id,
        user_id=None,
        title=widget_conversation_title(session_id),
    )
    msg = MagicMock(
        id=message_id,
        conversation_id=conversation_id,
        role="user",
        content="Giao hàng có tới quận 9 không?",
    )
    suggestion_read = MagicMock(id=uuid4(), question_text=msg.content)

    db = AsyncMock()
    msg_result = MagicMock()
    msg_result.scalar_one_or_none.return_value = msg

    with (
        patch(
            "app.services.shop_widget_conversation_service.conversation_repo.get_conversation_by_id",
            new=AsyncMock(return_value=conv),
        ),
        patch.object(db, "execute", new=AsyncMock(return_value=msg_result)),
        patch(
            "app.services.shop_widget_conversation_service.ShopWidgetConversationService._resolve_default_faq_kb_id",
            new=AsyncMock(return_value=kb_id),
        ),
        patch(
            "app.services.shop_widget_conversation_service.ShopFaqSuggestionService.promote_from_inbox",
            new=AsyncMock(return_value=suggestion_read),
        ) as promote_mock,
    ):
        result = await ShopWidgetConversationService(db).promote_message_to_faq_suggestion(
            organization_id=org_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )

    assert result == suggestion_read
    promote_mock.assert_awaited_once()


async def test_promote_rejects_assistant_message() -> None:
    tenant_id = uuid4()
    org_id = uuid4()
    conversation_id = uuid4()
    message_id = uuid4()
    session_id = uuid4()

    conv = MagicMock(
        organization_id=org_id,
        user_id=None,
        title=widget_conversation_title(session_id),
    )
    msg = MagicMock(
        id=message_id,
        role="assistant",
        content="Dạ shop giao 3–5 ngày.",
    )
    msg_result = MagicMock()
    msg_result.scalar_one_or_none.return_value = msg
    db = AsyncMock()

    with (
        patch(
            "app.services.shop_widget_conversation_service.conversation_repo.get_conversation_by_id",
            new=AsyncMock(return_value=conv),
        ),
        patch.object(db, "execute", new=AsyncMock(return_value=msg_result)),
    ):
        with pytest.raises(BadRequestError, match="Only customer messages"):
            await ShopWidgetConversationService(db).promote_message_to_faq_suggestion(
                organization_id=org_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
            )
