"""Auto-provision org MCP row for minerp_internal_shop (Minerp tenant orgs)."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vault import current_key_version
from app.integrations.minerp_shop.constants import (
    DEFAULT_ORG_CONNECTION_LABEL,
    DEFAULT_ORG_CONNECTION_NAME,
    MINERP_INTERNAL_SHOP_CATALOG_KEY,
    MINERP_INTERNAL_SHOP_URL,
)
from app.repositories import mcp_connection_repo

logger = logging.getLogger(__name__)


async def ensure_minerp_shop_mcp_for_org(
    db: AsyncSession,
    *,
    organization_id: UUID,
    created_by_user_id: UUID,
) -> None:
    """Idempotent org-scoped internal shop MCP connection."""
    existing = await mcp_connection_repo.get_org_scoped_by_catalog_key(
        db,
        organization_id=organization_id,
        catalog_key=MINERP_INTERNAL_SHOP_CATALOG_KEY,
    )
    if existing is not None:
        if not existing.is_enabled:
            await mcp_connection_repo.update(
                db,
                db_connection=existing,
                update_data={"is_enabled": True},
            )
        return

    by_name = await mcp_connection_repo.get_org_scoped_by_name(
        db,
        organization_id=organization_id,
        name=DEFAULT_ORG_CONNECTION_NAME,
    )
    if by_name is not None:
        return

    await mcp_connection_repo.create_org_scoped(
        db,
        organization_id=organization_id,
        created_by_user_id=created_by_user_id,
        name=DEFAULT_ORG_CONNECTION_NAME,
        url=MINERP_INTERNAL_SHOP_URL,
        sealed_token=None,
        secret_key_version=current_key_version(),
        allowed_tools=None,
        catalog_key=MINERP_INTERNAL_SHOP_CATALOG_KEY,
        is_enabled=True,
        label=DEFAULT_ORG_CONNECTION_LABEL,
    )
    logger.info(
        "minerp_internal_shop_mcp_provisioned",
        extra={"organization_id": str(organization_id)},
    )
