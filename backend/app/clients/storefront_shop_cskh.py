"""HTTP client for Shop CSKH read tools via storefront BFF internal routes."""

from __future__ import annotations

import json
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.core.exceptions import ExternalServiceError, NotFoundError


def _resolve_bff_base_url(tenant_id: str) -> str:
    raw = (settings.SHOP_CSKH_BFF_TENANT_MAP or "").strip()
    if raw:
        try:
            mapping = json.loads(raw)
        except json.JSONDecodeError:
            mapping = None
        if isinstance(mapping, dict):
            for key in (tenant_id, tenant_id.lower()):
                hit = mapping.get(key)
                if hit:
                    return str(hit).rstrip("/")
    return (settings.SHOP_CSKH_BFF_BASE_URL or "").rstrip("/")


def shop_cskh_bff_configured(*, tenant_id: str) -> bool:
    base = _resolve_bff_base_url(tenant_id)
    key = (settings.SHOP_CSKH_BFF_API_KEY or "").strip()
    return bool(base and key)


def shop_cskh_bff_base_url(*, tenant_id: str) -> str:
    return _resolve_bff_base_url(tenant_id)


def shop_cskh_bff_request_headers(*, tenant_id: str) -> dict[str, str]:
    return _headers(tenant_id=tenant_id)


def _headers(*, tenant_id: str) -> dict[str, str]:
    return {
        settings.API_KEY_HEADER: settings.SHOP_CSKH_BFF_API_KEY,
        "X-Tenant-Id": tenant_id,
    }


async def _get_json(*, path: str, tenant_id: str) -> dict:
    if not shop_cskh_bff_configured(tenant_id=tenant_id):
        raise ExternalServiceError(
            message="Shop CSKH BFF client not configured",
            details={
                "tenant_id": tenant_id,
                "base_url": _resolve_bff_base_url(tenant_id) or "(empty)",
            },
        )
    base = _resolve_bff_base_url(tenant_id)
    prefix = (settings.SHOP_CSKH_BFF_API_PREFIX or "/api/v1").rstrip("/")
    url = f"{base}{prefix}{path}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=_headers(tenant_id=tenant_id))
    except httpx.HTTPError as exc:
        raise ExternalServiceError(
            message="Shop BFF request failed",
            details={"url": url, "error": str(exc)},
        ) from exc
    if response.status_code == 404:
        raise NotFoundError(message="Shop resource not found", details={"url": url})
    if response.status_code != 200:
        raise ExternalServiceError(
            message="Shop BFF error",
            details={"url": url, "status": response.status_code, "body": response.text[:300]},
        )
    payload = response.json()
    return payload if isinstance(payload, dict) else {"data": payload}


async def get_shop_order(*, tenant_id: str, order_ref: str) -> dict:
    safe_ref = order_ref.strip()
    return await _get_json(path=f"/internal/shop-ai/orders/{safe_ref}", tenant_id=tenant_id)


async def get_shop_order_by_status_token(*, tenant_id: str, status_token: str) -> dict:
    params = urlencode({"token": status_token.strip()})
    return await _get_json(
        path=f"/internal/shop-ai/orders/status-by-token?{params}",
        tenant_id=tenant_id,
    )


async def get_shop_product(*, tenant_id: str, product_ref: str) -> dict:
    return await _get_json(
        path=f"/internal/shop-ai/products/{product_ref.strip()}",
        tenant_id=tenant_id,
    )


async def search_shop_products(*, tenant_id: str, query: str, limit: int = 5) -> dict:
    params = urlencode({"q": query.strip(), "limit": limit})
    return await _get_json(path=f"/internal/shop-ai/products?{params}", tenant_id=tenant_id)


async def get_shop_bestsellers(*, tenant_id: str, limit: int = 8, days: int = 30) -> dict:
    params = urlencode({"limit": limit, "days": days})
    return await _get_json(path=f"/internal/shop-ai/bestsellers?{params}", tenant_id=tenant_id)


async def list_shop_catalog_items(*, tenant_id: str, limit: int = 8) -> dict:
    params = urlencode({"limit": limit})
    return await _get_json(path=f"/internal/shop-ai/catalog/items?{params}", tenant_id=tenant_id)


async def get_catalog_item(*, tenant_id: str, item_id: str) -> dict:
    safe_id = item_id.strip()
    return await _get_json(
        path=f"/internal/shop-ai/catalog/items/{safe_id}",
        tenant_id=tenant_id,
    )


async def list_catalog_items(
    *,
    tenant_id: str,
    cursor: int = 0,
    limit: int = 100,
    active_only: bool = True,
) -> dict:
    params = f"cursor={cursor}&limit={limit}&active_only={'true' if active_only else 'false'}"
    return await _get_json(path=f"/internal/shop-ai/catalog/items?{params}", tenant_id=tenant_id)


def format_tool_result(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def format_product_search(payload: dict) -> str:
    if payload.get("error"):
        details = payload.get("details")
        suffix = f" ({details})" if details else ""
        return f"Catalog search error: {payload['error']}{suffix}"
    items = payload.get("items") or []
    if not items:
        return "No matching products found in the shop catalog."
    lines = [f"Found {len(items)} product(s):"]
    for i, item in enumerate(items, start=1):
        name = item.get("name") or "Product"
        item_id = item.get("id") or "unknown"
        sku = item.get("sku")
        sku_line = f", SKU: {sku}" if sku else ""
        lines.append(f"[{i}] {name} (ID: {item_id}{sku_line})")
    return "\n".join(lines)


def format_bestsellers(payload: dict) -> str:
    if payload.get("error"):
        details = payload.get("details")
        suffix = f" ({details})" if details else ""
        return f"Bestseller lookup error: {payload['error']}{suffix}"
    items = payload.get("items") or []
    days = payload.get("days") or 30
    if not items:
        return f"No WEB order data in the last {days} day(s) to rank bestsellers."
    lines = [f"Top sellers (last {days} days):"]
    for i, item in enumerate(items, start=1):
        name = item.get("name") or "Product"
        item_id = item.get("id") or "unknown"
        qty = item.get("qty_sum")
        orders = item.get("order_count")
        stat = f", {qty} units in {orders} orders" if qty is not None and orders else ""
        lines.append(f"[{i}] {name} (ID: {item_id}{stat})")
    return "\n".join(lines)
