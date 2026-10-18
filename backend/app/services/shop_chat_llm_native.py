"""B82 — widget/merchant chat LLM on Agentra before multi-agent strangler."""

from __future__ import annotations

from app.core.config import settings
from app.schemas.shop_llm_generate import ShopLlmGenerateIn
from app.services.shop_llm_generate import ShopLlmGenerateService
from app.services.shop_llm_openai import shop_llm_generate_configured

_WIDGET_SYSTEM = (
    "Bạn là trợ lý CSKH shop (tiếng Việt, ngắn gọn, lịch sự). "
    "Trả lời câu hỏi khách trên widget chat."
)
_MERCHANT_SYSTEM = (
    "Bạn là trợ lý merchant shop (tiếng Việt, ngắn gọn). "
    "Giúp chủ shop tra đơn, sản phẩm, bán chạy khi được hỏi."
)


def shop_widget_llm_on_agentra_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_WIDGET_LLM_ON_AGENTRA


def shop_merchant_llm_on_agentra_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_MERCHANT_LLM_ON_AGENTRA


async def try_widget_chat_llm_on_agentra(*, message: str) -> str | None:
    if not shop_widget_llm_on_agentra_enabled() or not shop_llm_generate_configured():
        return None
    prompt = f"{_WIDGET_SYSTEM}\n\nKhách: {(message or '').strip()}\n\nTrả lời:"
    try:
        out = await ShopLlmGenerateService().generate(ShopLlmGenerateIn(prompt=prompt))
        body = (out.body or "").strip()
        return body or None
    except Exception:
        return None


async def try_merchant_chat_llm_on_agentra(*, message: str) -> str | None:
    if not shop_merchant_llm_on_agentra_enabled() or not shop_llm_generate_configured():
        return None
    prompt = f"{_MERCHANT_SYSTEM}\n\nMerchant: {(message or '').strip()}\n\nTrả lời:"
    try:
        out = await ShopLlmGenerateService().generate(ShopLlmGenerateIn(prompt=prompt))
        body = (out.body or "").strip()
        return body or None
    except Exception:
        return None
