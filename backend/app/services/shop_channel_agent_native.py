"""B80 — PydanticAI shop CSKH tools on Zalo/Messenger (no multi-agent widget/chat)."""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic_ai import Agent
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.deps import AgentDeps
from app.core.config import settings
from app.integrations.minerp_shop.constants import SHOP_TOOL_NAMES
from app.integrations.minerp_shop.toolset import build_minerp_internal_shop_toolset
from app.services.shop_channel_llm_strangler import _build_channel_prompt
from app.services.shop_llm_openai import build_shop_llm_generate_model, shop_llm_generate_configured

logger = logging.getLogger(__name__)

_CHANNEL_AGENT_SYSTEM = (
    "Bạn là trợ lý CSKH shop trên Zalo/Messenger (tiếng Việt, ngắn gọn, lịch sự). "
    "Dùng công cụ tra đơn, sản phẩm, bán chạy khi khách hỏi chi tiết. "
    "Chỉ trả lời nội dung gửi cho khách, không markdown phức tạp."
)


def shop_channel_agent_native_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_CHANNEL_AGENT_ENABLED


async def try_shop_channel_agent_native_reply(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    message: str,
    organization_id: UUID | None = None,
) -> str | None:
    if not shop_channel_agent_native_enabled():
        return None
    if not shop_llm_generate_configured():
        return None
    prompt = await _build_channel_prompt(
        db,
        conversation_id=conversation_id,
        message=message,
    )
    toolset = build_minerp_internal_shop_toolset(
        connection_name="shop-channel",
        allowed_tools=list(SHOP_TOOL_NAMES),
    )
    agent: Agent[AgentDeps, str] = Agent(
        model=build_shop_llm_generate_model(),
        deps_type=AgentDeps,
        toolsets=[toolset],
        system_prompt=_CHANNEL_AGENT_SYSTEM,
    )
    deps = AgentDeps(
        minerp_tenant_id=tenant_id,
        organization_id=organization_id,
    )
    try:
        result = await agent.run(prompt, deps=deps)
        reply = str(result.output or "").strip()
        return reply or None
    except Exception:
        logger.exception("shop_channel_agent_native_failed tenant=%s", tenant_id)
        return None
