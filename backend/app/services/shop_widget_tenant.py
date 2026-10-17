"""Resolve Minerp shop tenant → Agentra organization."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.organization import Organization
from app.repositories import organization_repo


async def require_org_for_shop_tenant(db: AsyncSession, tenant_id: UUID) -> Organization:
    org = await organization_repo.get_by_minerp_tenant_id(db, tenant_id)
    if org is None:
        raise NotFoundError(
            message="No organization linked to shop tenant",
            details={"tenant_id": str(tenant_id)},
        )
    return org
