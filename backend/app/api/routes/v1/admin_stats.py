"""Admin observability - workspace stats and per-service health."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import AdminSvc, CurrentAdmin, DBSession, Redis
from app.schemas.admin import AdminStats
from app.schemas.health import SystemHealthResponse
from app.services.health import system_health

router = APIRouter()


@router.get("/stats", response_model=AdminStats)
async def get_admin_stats(
    service: AdminSvc,
    _user: CurrentAdmin,
) -> Any:
    """Aggregate workspace metrics."""
    return await service.workspace_stats()


@router.get("/system", response_model=SystemHealthResponse)
async def get_system_health(
    db: DBSession,
    redis: Redis,
    _user: CurrentAdmin,
) -> Any:
    """Per-service health for the admin system page.

    Separate from ``/health/ready`` on purpose. That endpoint is a readiness
    probe - unauthenticated, and answering a load balancer's question - and
    serving a dashboard from it is what previously put a Stripe row and an
    unprobed vector store on a page operators were expected to trust. Here every
    check carries the detail of what was actually verified, because an admin
    session is what makes that safe to publish.
    """
    return await system_health(db=db, redis=redis)
