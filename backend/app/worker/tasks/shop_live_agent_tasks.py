"""Shop AI live-agent background maintenance (D3 B54)."""

from __future__ import annotations

import logging

from prefect import flow

from app.db.session import get_worker_db_context
from app.services.shop_live_agent_inbox import release_idle_human_sessions_all_shop_orgs

logger = logging.getLogger(__name__)


@flow(name="shop-live-agent-idle-release")
async def shop_live_agent_idle_release_flow() -> dict[str, int]:
    async with get_worker_db_context() as db:
        try:
            return await release_idle_human_sessions_all_shop_orgs(db)
        except Exception:
            logger.exception("Shop AI idle auto-release flow failed")
            raise
