"""B72 — LLM reply for Zalo/Messenger when deterministic widget path misses."""

from __future__ import annotations

import json
import logging
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ExternalServiceError
from app.repositories import conversation_repo
from app.schemas.shop_llm_generate import ShopLlmGenerateIn
from app.services.multi_agent_shop_proxy import (
    SHOP_AI_LLM_PROXY_TIMEOUT_SEC,
    _multi_agent_base_and_key,
    _upstream_url,
)
from app.services.shop_llm_generate import ShopLlmGenerateService
from app.services.shop_llm_openai import shop_llm_generate_configured

logger = logging.getLogger(__name__)


def shop_channel_llm_strangler_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_CHANNEL_LLM_STRANGLER


async def try_shop_channel_llm_reply(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    message: str,
) -> str | None:
    """One-shot LLM CSKH reply using native generate or multi-agent llm-generate proxy."""
    if not shop_channel_llm_strangler_enabled():
        return None

    prompt = await _build_channel_prompt(db, conversation_id=conversation_id, message=message)
    if shop_llm_generate_configured():
        try:
            out = await ShopLlmGenerateService().generate(ShopLlmGenerateIn(prompt=prompt))
            body = (out.body or "").strip()
            return body or None
        except Exception:
            logger.exception("shop_channel_llm_native_failed tenant=%s", tenant_id)

    try:
        payload = await _post_multi_agent_llm_generate(tenant_id=tenant_id, prompt=prompt)
        body = str(payload.get("body") or "").strip()
        return body or None
    except ExternalServiceError:
        return None
    except Exception:
        logger.exception("shop_channel_llm_strangler_failed tenant=%s", tenant_id)
        return None


async def _build_channel_prompt(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    message: str,
) -> str:
    messages = await conversation_repo.get_messages_by_conversation(
        db,
        conversation_id,
        skip=0,
        limit=12,
    )
    lines: list[str] = []
    for row in messages:
        label = "Khách" if row.role == "user" else "Shop"
        content = (row.content or "").strip()
        if content:
            lines.append(f"{label}: {content}")
    user_line = (message or "").strip()
    if user_line:
        lines.append(f"Khách: {user_line}")
    transcript = "\n".join(lines) if lines else user_line
    return (
        "Bạn là trợ lý CSKH shop (tiếng Việt, ngắn gọn, lịch sự). "
        "Trả lời tin nhắn mới nhất của khách dựa trên hội thoại:\n\n"
        f"{transcript}\n\n"
        "Trả lời (chỉ nội dung gửi cho khách, không markdown phức tạp):"
    )


async def _post_multi_agent_llm_generate(*, tenant_id: UUID, prompt: str) -> dict:
    _, api_key = _multi_agent_base_and_key()
    url = _upstream_url("llm-generate", "")
    headers = {
        settings.API_KEY_HEADER: api_key,
        "X-Tenant-Id": str(tenant_id),
        "Content-Type": "application/json",
    }
    body = json.dumps({"prompt": prompt, "include_subject": False}).encode()
    timeout = httpx.Timeout(SHOP_AI_LLM_PROXY_TIMEOUT_SEC)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers, content=body)
    if response.status_code >= 400:
        raise ExternalServiceError(
            message="Shop AI llm-generate upstream error",
            details={"status_code": response.status_code},
        )
    data = response.json()
    if not isinstance(data, dict):
        raise ExternalServiceError(
            message="Shop AI llm-generate invalid response",
            details={},
        )
    return data
