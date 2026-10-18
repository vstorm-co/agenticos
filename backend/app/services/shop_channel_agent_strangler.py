"""B78 — full shop CSKH agent on channel via multi-agent widget/chat proxy."""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.config import settings
from app.core.exceptions import ExternalServiceError
from app.services.multi_agent_shop_proxy import post_shop_ai_json

logger = logging.getLogger(__name__)


def shop_channel_agent_strangler_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_CHANNEL_AGENT_STRANGLER


async def try_shop_channel_agent_strangler_reply(
    *,
    tenant_id: UUID,
    session_id: UUID,
    message: str,
    kb_id: UUID | None,
    organization_id: UUID | None = None,
) -> str | None:
    """Invoke multi-agent widget/chat (tools + agent) for Zalo/Messenger."""
    if not shop_channel_agent_strangler_enabled():
        return None
    body = {
        "message": message,
        "session_id": str(session_id),
    }
    if kb_id is not None:
        body["kb_id"] = str(kb_id)
    try:
        payload = await post_shop_ai_json(
            subpath="widget/chat",
            tenant_id=tenant_id,
            payload=body,
            organization_id=organization_id,
        )
    except ExternalServiceError:
        return None
    except Exception:
        logger.exception("shop_channel_agent_strangler_failed tenant=%s", tenant_id)
        return None
    reply = str(payload.get("reply") or "").strip()
    return reply or None
