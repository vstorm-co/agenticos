"""B78 — channel agent strangler."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.shop_channel_agent_strangler import try_shop_channel_agent_strangler_reply

pytestmark = pytest.mark.anyio


async def test_agent_strangler_returns_reply() -> None:
    tenant_id = uuid4()
    session_id = uuid4()
    with (
        patch(
            "app.services.shop_channel_agent_strangler.shop_channel_agent_strangler_enabled",
            return_value=True,
        ),
        patch(
            "app.services.shop_channel_agent_strangler.post_shop_ai_json",
            new=AsyncMock(return_value={"reply": "Xin chào"}),
        ),
    ):
        out = await try_shop_channel_agent_strangler_reply(
            tenant_id=tenant_id,
            session_id=session_id,
            message="hi",
            kb_id=None,
        )
    assert out == "Xin chào"
