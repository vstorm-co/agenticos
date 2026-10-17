"""D3 — native Shop AI reads on Agentra via storefront BFF (extension SoR)."""

from __future__ import annotations

import logging
from uuid import UUID

import httpx
from starlette.requests import Request
from starlette.responses import Response

from app.clients import storefront_shop_cskh as shop_client
from app.core.config import settings
from app.core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


def is_bff_native_read_subpath(subpath: str, method: str) -> bool:
    """GET paths implemented on `apps/storefront` internal shop-ai (not multi-agent)."""
    if method.upper() != "GET":
        return False
    path = subpath.strip("/")
    if path in {"site-path", "bestsellers"}:
        return True
    if path == "orders/status-by-token" or path.startswith("orders/"):
        return True
    if path == "products" or path.startswith("products/"):
        return True
    if path == "catalog/items" or path.startswith("catalog/items/"):
        return True
    return False


async def maybe_proxy_bff_native_read(
    *,
    request: Request,
    subpath: str,
    tenant_id: UUID,
) -> Response | None:
    """Forward to storefront BFF when configured; otherwise fall through to strangler."""
    if not settings.SHOP_AI_NATIVE_BFF_READS_ENABLED:
        return None
    if not is_bff_native_read_subpath(subpath, request.method):
        return None
    tenant_str = str(tenant_id)
    if not shop_client.shop_cskh_bff_configured(tenant_id=tenant_str):
        return None

    prefix = (settings.SHOP_CSKH_BFF_API_PREFIX or "/api/v1").rstrip("/")
    path_part = subpath.strip("/")
    url_path = f"{prefix}/internal/shop-ai/{path_part}"
    base = shop_client.shop_cskh_bff_base_url(tenant_id=tenant_str)
    url = f"{base}{url_path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = shop_client.shop_cskh_bff_request_headers(tenant_id=tenant_str)
    accept = request.headers.get("accept")
    if accept:
        headers["Accept"] = accept

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            upstream = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning(
            "shop_ai_bff_native_read_failed",
            extra={"tenant_id": tenant_str, "subpath": subpath},
            exc_info=True,
        )
        raise ExternalServiceError(
            message="Shop BFF read unavailable",
            details={"subpath": subpath, "url": url, "error": str(exc)},
        ) from exc

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type") or "application/json",
    )
