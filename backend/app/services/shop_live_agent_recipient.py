"""Resolve customer_care staff for Shop live-agent (D3 B53)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.minerp_auth_role_users import CS_ROLE_CODES, fetch_tenant_user_ids_by_role_codes


async def list_customer_care_user_ids(
    db: AsyncSession,
    *,
    tenant_id: UUID,
) -> list[UUID]:
    del db
    ids = await fetch_tenant_user_ids_by_role_codes(tenant_id, role_codes=CS_ROLE_CODES)
    if ids is None:
        return []
    return sorted(ids, key=str)
