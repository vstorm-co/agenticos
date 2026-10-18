"""Resolve Minerp IAM users by RBAC role (services/auth internal API)."""

from __future__ import annotations

import logging
from uuid import UUID

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

CS_ROLE_CODES = ("customer_care",)


async def fetch_tenant_user_ids_by_role_codes(
    tenant_id: UUID,
    *,
    role_codes: tuple[str, ...] | list[str],
) -> list[UUID] | None:
    """Return user ids, or None when lookup is disabled/unavailable."""
    if not settings.MINERP_AUTH_TENANT_LOOKUP_ENABLED:
        return None
    api_key = (settings.MINERP_AUTH_INTERNAL_API_KEY or "").strip()
    if not api_key:
        return None
    codes = [c.strip() for c in role_codes if c and str(c).strip()]
    if not codes:
        return []
    base = settings.IAM_AUTH_INTERNAL_BASE_URL.rstrip("/")
    url = f"{base}/api/v1/internal/tenants/{tenant_id}/users-by-role"
    headers = {settings.API_KEY_HEADER: api_key}
    params = [("role_codes", code) for code in codes]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers, params=params)
    except httpx.HTTPError:
        logger.warning(
            "minerp_auth_role_users_lookup_failed",
            extra={"tenant_id": str(tenant_id), "role_codes": codes},
            exc_info=True,
        )
        return None
    if response.status_code == 404:
        return []
    if response.status_code != 200:
        logger.warning(
            "minerp_auth_role_users_bad_status",
            extra={
                "tenant_id": str(tenant_id),
                "status": response.status_code,
            },
        )
        return None
    try:
        payload = response.json()
        raw = payload.get("user_ids") or []
        return [UUID(str(x)) for x in raw]
    except (TypeError, ValueError):
        return None
