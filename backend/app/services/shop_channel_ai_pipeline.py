"""Channel inbound AI leg labels for ops matrix (B81)."""

from __future__ import annotations

from app.core.config import Settings, settings
from app.services.shop_channel_agent_native import shop_channel_agent_native_enabled
from app.services.shop_channel_agent_strangler import shop_channel_agent_strangler_enabled
from app.services.shop_channel_llm_strangler import shop_channel_llm_strangler_enabled
from app.services.shop_llm_openai import shop_llm_generate_configured


def channel_inbound_ai_pipeline_note(cfg: Settings | None = None) -> str:
    """Describe Zalo/Messenger AI stack after deterministic widget path."""
    cfg = cfg or settings
    legs: list[str] = []
    if cfg.SHOP_AI_NATIVE_WIDGET_ENABLED:
        legs.append("widget-native")
    else:
        legs.append("widget-proxy")
    if shop_channel_llm_strangler_enabled():
        legs.append("channel-LLM")
    if shop_channel_agent_native_enabled() and shop_llm_generate_configured():
        legs.append("native shop tools")
    elif shop_channel_agent_strangler_enabled():
        legs.append("multi-agent widget/chat")
    return " → ".join(legs)
