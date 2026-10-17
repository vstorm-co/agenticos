"""Background FAQ draft when customer questions repeat (D3 B58)."""

from __future__ import annotations

import logging
from uuid import UUID

from app.db.session import get_worker_db_context
from app.services.shop_faq_suggestion import ShopFaqSuggestionService

logger = logging.getLogger(__name__)


async def run_faq_auto_draft_background(
    *,
    organization_id: UUID,
    minerp_tenant_id: UUID,
    kb_id: UUID,
    suggestion_id: UUID,
) -> None:
    async with get_worker_db_context() as db:
        drafted = await ShopFaqSuggestionService(db).auto_draft_pending_suggestion(
            organization_id=organization_id,
            minerp_tenant_id=minerp_tenant_id,
            kb_id=kb_id,
            suggestion_id=suggestion_id,
        )
    logger.info(
        "FAQ auto-draft suggestion=%s tenant=%s drafted=%s",
        suggestion_id,
        minerp_tenant_id,
        drafted,
    )
