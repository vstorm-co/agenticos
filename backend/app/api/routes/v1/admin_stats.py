"""Admin observability - workspace stats and per-service health."""

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import AdminSvc, CurrentAppAdmin, DBSession, Redis
from app.schemas.admin import AdminOrganizationList, AdminStats
from app.schemas.health import SystemHealthResponse
from app.services.health import system_health

router = APIRouter()


@router.get("/stats", response_model=AdminStats)
async def get_admin_stats(
    service: AdminSvc,
    _user: CurrentAppAdmin,
) -> Any:
    """Aggregate workspace metrics."""
    return await service.workspace_stats()


@router.get("/organizations", response_model=AdminOrganizationList)
async def list_admin_organizations(
    service: AdminSvc,
    _user: CurrentAppAdmin,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Every organization in the deployment, with member and agent counts.

    Cross-tenant by design: the platform admin administers the deployment, and
    this is the only surface that answers "what tenants exist" at all.
    """
    return await service.list_organizations(skip=skip, limit=limit)


@router.get("/system", response_model=SystemHealthResponse)
async def get_system_health(
    db: DBSession,
    redis: Redis,
    _user: CurrentAppAdmin,
) -> Any:
    """Per-service health for the admin system page.

    Separate from `/health/ready` on purpose. That endpoint is a readiness
    probe - unauthenticated, and answering a load balancer's question - and
    serving a dashboard from it is what previously put a Stripe row and an
    unprobed vector store on a page operators were expected to trust. Here every
    check carries the detail of what was actually verified, because an admin
    session is what makes that safe to publish.
    """
    return await system_health(db=db, redis=redis)
