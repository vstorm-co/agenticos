"""Resolve Minerp tenant UUID ↔ Agentra organization (read-only)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories import organization_repo
from app.schemas.minerp_integration import MinerpTenantContextRead


def _to_read(org) -> MinerpTenantContextRead:
    if org.minerp_tenant_id is None:
        raise NotFoundError(
            message="Organization is not linked to a Minerp tenant",
            details={"organization_id": str(org.id)},
        )
    return MinerpTenantContextRead(
        organization_id=org.id,
        minerp_tenant_id=org.minerp_tenant_id,
        organization_name=org.name,
        organization_slug=org.slug,
        is_personal=org.is_personal,
    )


async def tenant_context_for_organization(
    db: AsyncSession, organization_id: UUID
) -> MinerpTenantContextRead:
    org = await organization_repo.get_by_id(db, organization_id)
    if org is None:
        raise NotFoundError(
            message="Organization not found", details={"organization_id": str(organization_id)}
        )
    return _to_read(org)


async def tenant_context_for_minerp_tenant(
    db: AsyncSession, tenant_id: UUID
) -> MinerpTenantContextRead:
    org = await organization_repo.get_by_minerp_tenant_id(db, tenant_id)
    if org is None:
        raise NotFoundError(
            message="No Agentra organization linked to Minerp tenant",
            details={"minerp_tenant_id": str(tenant_id)},
        )
    return _to_read(org)
