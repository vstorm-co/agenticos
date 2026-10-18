"""Read Minerp IAM tenant registry (services/auth) for org display names."""

from __future__ import annotations

import logging
from uuid import UUID

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def fetch_minerp_tenant_display_name(tenant_id: UUID) -> str | None:
    """Return tenant `name` from auth internal API, or None if lookup is disabled/unavailable."""
    if not settings.MINERP_AUTH_TENANT_LOOKUP_ENABLED:
        return None
    api_key = (settings.MINERP_AUTH_INTERNAL_API_KEY or "").strip()
    if not api_key:
        return None
    base = settings.IAM_AUTH_INTERNAL_BASE_URL.rstrip("/")
    url = f"{base}/api/v1/internal/tenants/{tenant_id}"
    headers = {settings.API_KEY_HEADER: api_key}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError:
        logger.warning(
            "minerp_auth_tenant_lookup_failed",
            extra={"tenant_id": str(tenant_id)},
            exc_info=True,
        )
        return None
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        logger.warning(
            "minerp_auth_tenant_lookup_bad_status",
            extra={"tenant_id": str(tenant_id), "status": response.status_code},
        )
        return None
    try:
        payload = response.json()
        name = str(payload.get("name") or "").strip()
    except (TypeError, ValueError):
        return None
    return name or None
