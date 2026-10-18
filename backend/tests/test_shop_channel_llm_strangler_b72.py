"""B72 — channel LLM strangler prompt + native path."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.config import settings
from app.services.shop_channel_llm_strangler import (
    _build_channel_prompt,
    try_shop_channel_llm_reply,
)

pytestmark = pytest.mark.anyio


async def test_build_channel_prompt_includes_user_message() -> None:
    db = MagicMock()
    conv_id = uuid4()

    class Msg:
        def __init__(self, role: str, content: str) -> None:
            self.role = role
            self.content = content

    with patch(
        "app.services.shop_channel_llm_strangler.conversation_repo.get_messages_by_conversation",
        new=AsyncMock(return_value=[Msg("user", "Alo shop")]),
    ):
        prompt = await _build_channel_prompt(
            db,
            conversation_id=conv_id,
            message="Con hang nay gia bao nhieu",
        )

    assert "Alo shop" in prompt
    assert "Con hang nay gia bao nhieu" in prompt


async def test_try_llm_uses_native_when_configured() -> None:
    db = MagicMock()
    tenant_id = uuid4()
    conv_id = uuid4()

    with (
        patch.object(settings, "SHOP_AI_NATIVE_CHANNEL_LLM_STRANGLER", True),
        patch(
            "app.services.shop_channel_llm_strangler.shop_llm_generate_configured",
            return_value=True,
        ),
        patch(
            "app.services.shop_channel_llm_strangler._build_channel_prompt",
            new=AsyncMock(return_value="prompt"),
        ),
        patch(
            "app.services.shop_channel_llm_strangler.ShopLlmGenerateService"
        ) as svc_cls,
    ):
        svc_cls.return_value.generate = AsyncMock(
            return_value=MagicMock(body="Dạ em báo giá ạ")
        )
        out = await try_shop_channel_llm_reply(
            db,
            tenant_id=tenant_id,
            conversation_id=conv_id,
            message="gia",
        )

    assert out == "Dạ em báo giá ạ"
