"""Health check endpoints.

Provides Kubernetes-compatible health check endpoints:
- /health - Simple liveness check
- /health/live - Detailed liveness probe
- /health/ready - Readiness probe with dependency checks
"""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.api.deps import DBSession, Redis
from app.core.config import settings
from app.schemas.base import HealthDetailResponse, HealthResponse
from app.services.health import build_health_response, readiness

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> dict[str, Any]:
    """Simple liveness probe - check if application is running.

    This is a lightweight check that should always succeed if the
    application is running. Use this for basic connectivity tests.

    Returns:
        {"status": "healthy"}
    """
    return {
        "status": "healthy",
        "max_upload_size_mb": settings.MAX_UPLOAD_SIZE_MB,
    }


@router.get("/health/live", response_model=HealthDetailResponse)
async def liveness_probe() -> dict[str, Any]:
    """Detailed liveness probe for Kubernetes.

    This endpoint is designed for Kubernetes liveness probes.
    It checks if the application process is alive and responding.
    Failure indicates the container should be restarted.

    Returns:
        Structured response with timestamp and service info.
    """
    return build_health_response(
        status="alive",
        details={
            "version": getattr(settings, "VERSION", "1.0.0"),
            "environment": settings.ENVIRONMENT,
        },
    )


@router.get("/health/ready", response_model=None)
async def readiness_probe(
    db: DBSession,
    redis: Redis,
) -> dict[str, Any] | JSONResponse:
    """Readiness probe for Kubernetes.

    Reports whether the dependencies a request cannot proceed without are
    answering: the database and Redis. Failure means traffic should be diverted
    from this instance.

    Nothing else belongs here. This endpoint takes no credential, so it says
    only what it is willing to tell a stranger - a status and a latency per
    check, with the reason for a failure in the log rather than the body. The
    deployment's own configuration (the vector store, whether any organization
    can reach a model) is an operator's question, not a load balancer's, and it
    is answered by `GET /admin/system` behind an admin session.

    Returns:
        The per-check statuses, and 503 when either check is not healthy.
    """
    ready, checks = await readiness(db=db, redis=redis)
    response_data = build_health_response(
        status="ready" if ready else "not_ready",
        checks=checks,
    )
    if not ready:
        return JSONResponse(status_code=503, content=response_data)

    return response_data


# Backward compatibility - keep /ready endpoint
@router.get("/ready", response_model=None)
async def readiness_check(
    db: DBSession,
    redis: Redis,
) -> dict[str, Any] | JSONResponse:
    """Readiness check (alias for /health/ready).

    Deprecated: Use /health/ready instead.
    """
    return await readiness_probe(
        db=db,
        redis=redis,
    )
