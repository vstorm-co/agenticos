"""B82 — widget/merchant LLM on Agentra."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.shop_chat_llm_native import try_widget_chat_llm_on_agentra

pytestmark = pytest.mark.anyio


async def test_widget_llm_native_returns_body() -> None:
    with (
        patch(
            "app.services.shop_chat_llm_native.shop_widget_llm_on_agentra_enabled",
            return_value=True,
        ),
        patch(
            "app.services.shop_chat_llm_native.shop_llm_generate_configured",
            return_value=True,
        ),
        patch(
            "app.services.shop_chat_llm_native.ShopLlmGenerateService"
        ) as svc_cls,
    ):
        svc_cls.return_value.generate = AsyncMock(
            return_value=type("O", (), {"body": "Xin chao"})()
        )
        out = await try_widget_chat_llm_on_agentra(message="hello")
    assert out == "Xin chao"
