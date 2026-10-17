"""Shop CSKH tools — tenant scope from AgentDeps.minerp_tenant_id only."""

from __future__ import annotations

import re

from pydantic_ai import RunContext

from app.agents.deps import AgentDeps
from app.clients import storefront_shop_cskh as shop_client
from app.core.exceptions import AppException
from app.integrations.minerp_shop.product_query import catalog_search_candidates

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _tenant_id_str(ctx: RunContext[AgentDeps]) -> str | None:
    tid = ctx.deps.minerp_tenant_id
    return str(tid) if tid is not None else None


async def lookup_shop_order(ctx: RunContext[AgentDeps], order_ref: str) -> str:
    """Look up order by guest status token or internal order UUID for this shop tenant."""
    tenant_id = _tenant_id_str(ctx)
    if not tenant_id:
        return shop_client.format_tool_result({"error": "Minerp shop tenant context missing"})
    ref = (order_ref or "").strip()
    if not ref:
        return shop_client.format_tool_result(
            {
                "error": "Missing order reference",
                "hint": "Use guest status token from checkout email/SMS",
            }
        )
    try:
        if _UUID_RE.fullmatch(ref):
            payload = await shop_client.get_shop_order(tenant_id=tenant_id, order_ref=ref)
        else:
            payload = await shop_client.get_shop_order_by_status_token(
                tenant_id=tenant_id,
                status_token=ref,
            )
        return shop_client.format_tool_result(payload)
    except AppException as exc:
        return shop_client.format_tool_result({"error": exc.message, "details": exc.details})


async def lookup_shop_product(ctx: RunContext[AgentDeps], product_ref: str) -> str:
    """Look up a catalog product by name, SKU, or item UUID for this shop tenant."""
    tenant_id = _tenant_id_str(ctx)
    if not tenant_id:
        return shop_client.format_tool_result({"error": "Minerp shop tenant context missing"})
    try:
        payload = await shop_client.get_shop_product(tenant_id=tenant_id, product_ref=product_ref)
        return shop_client.format_tool_result(payload)
    except AppException as exc:
        return shop_client.format_tool_result({"error": exc.message, "details": exc.details})


async def search_shop_products(ctx: RunContext[AgentDeps], query: str, limit: int = 5) -> str:
    """Search the shop catalog by product name or keyword (Vietnamese OK)."""
    tenant_id = _tenant_id_str(ctx)
    if not tenant_id:
        return shop_client.format_product_search({"error": "Minerp shop tenant context missing"})
    try:
        merged_items: list[dict] = []
        seen_ids: set[str] = set()
        for candidate in catalog_search_candidates(query):
            payload = await shop_client.search_shop_products(
                tenant_id=tenant_id,
                query=candidate,
                limit=limit,
            )
            for item in payload.get("items") or []:
                item_id = str(item.get("id") or "")
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                merged_items.append(item)
            if merged_items:
                break
        return shop_client.format_product_search(
            {"items": merged_items[:limit], "total": len(merged_items[:limit])}
        )
    except AppException as exc:
        return shop_client.format_product_search({"error": exc.message, "details": exc.details})


async def list_shop_bestsellers(ctx: RunContext[AgentDeps], limit: int = 8, days: int = 30) -> str:
    """Top-selling products from real WEB orders in the last N days."""
    tenant_id = _tenant_id_str(ctx)
    if not tenant_id:
        return shop_client.format_bestsellers({"error": "Minerp shop tenant context missing"})
    try:
        payload = await shop_client.get_shop_bestsellers(
            tenant_id=tenant_id,
            limit=limit,
            days=days,
        )
        return shop_client.format_bestsellers(payload)
    except AppException as exc:
        return shop_client.format_bestsellers({"error": exc.message, "details": exc.details})
