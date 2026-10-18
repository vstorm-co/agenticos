"""Internal Minerp platform integration (BFF / multi-agent strangler)."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import DBSession, ValidAPIKey
from app.services.minerp_tenant_lookup import (
    tenant_context_for_minerp_tenant,
    tenant_context_for_organization,
)

router = APIRouter(prefix="/internal/minerp", tags=["internal:minerp"])


@router.get(
    "/organizations/by-tenant/{tenant_id}",
    response_model=None,
)
async def get_organization_by_minerp_tenant(
    tenant_id: UUID,
    _api_key: ValidAPIKey,
    db: DBSession,
) -> Any:
    return await tenant_context_for_minerp_tenant(db, tenant_id)


@router.get(
    "/tenant-by-organization/{organization_id}",
    response_model=None,
)
async def get_tenant_by_organization(
    organization_id: UUID,
    _api_key: ValidAPIKey,
    db: DBSession,
) -> Any:
    return await tenant_context_for_organization(db, organization_id)
