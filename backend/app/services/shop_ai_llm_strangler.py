"""B51 — explicit LLM strangler for widget + merchant chat (multi-agent upstream)."""

from __future__ import annotations

from uuid import UUID

from starlette.requests import Request

from app.core.config import settings
from app.services.multi_agent_shop_proxy import proxy_shop_ai_request


def shop_widget_llm_strangler_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_WIDGET_LLM_STRANGLER


def shop_merchant_llm_strangler_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_MERCHANT_LLM_STRANGLER


async def strangler_widget_chat(
    *,
    request: Request,
    tenant_id: UUID,
    body_json: bytes,
) -> object:
    return await proxy_shop_ai_request(
        request=request,
        subpath="widget/chat",
        tenant_id=tenant_id,
        body_override=body_json,
    )


async def strangler_merchant_chat(
    *,
    request: Request,
    tenant_id: UUID,
    body_json: bytes,
    stream: bool = False,
) -> object:
    subpath = "merchant-assistant/chat/stream" if stream else "merchant-assistant/chat"
    return await proxy_shop_ai_request(
        request=request,
        subpath=subpath,
        tenant_id=tenant_id,
        body_override=body_json,
    )
