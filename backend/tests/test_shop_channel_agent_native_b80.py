"""B80 — native channel agent with shop tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.shop_channel_agent_native import try_shop_channel_agent_native_reply

pytestmark = pytest.mark.anyio


async def test_native_agent_returns_reply() -> None:
    tenant_id = uuid4()
    conversation_id = uuid4()
    db = MagicMock()
    fake_run = MagicMock()
    fake_run.output = "Đơn của bạn đang giao"
    with (
        patch(
            "app.services.shop_channel_agent_native.shop_channel_agent_native_enabled",
            return_value=True,
        ),
        patch(
            "app.services.shop_channel_agent_native.shop_llm_generate_configured",
            return_value=True,
        ),
        patch(
            "app.services.shop_channel_agent_native._build_channel_prompt",
            new=AsyncMock(return_value="Khách: tra đơn"),
        ),
        patch(
            "app.services.shop_channel_agent_native.build_shop_llm_generate_model",
            return_value=MagicMock(),
        ),
        patch("app.services.shop_channel_agent_native.Agent") as agent_cls,
    ):
        agent_cls.return_value.run = AsyncMock(return_value=fake_run)
        out = await try_shop_channel_agent_native_reply(
            db,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message="tra đơn",
        )
    assert out == "Đơn của bạn đang giao"
