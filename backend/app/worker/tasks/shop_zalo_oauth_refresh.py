"""Zalo OA OAuth token refresh beat (D3 B76)."""

from __future__ import annotations

import logging

from prefect import flow

from app.db.session import get_worker_db_context
from app.services.shop_zalo_oauth_flow import refresh_expiring_shop_zalo_oauth_tokens

logger = logging.getLogger(__name__)


@flow(name="shop-zalo-oauth-refresh")
async def shop_zalo_oauth_refresh_flow() -> dict[str, int]:
    async with get_worker_db_context() as db:
        try:
            return await refresh_expiring_shop_zalo_oauth_tokens(db)
        except Exception:
            logger.exception("Shop Zalo OAuth refresh flow failed")
            raise
