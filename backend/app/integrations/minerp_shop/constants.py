"""Minerp platform internal MCP — shop CSKH (storefront BFF)."""

from __future__ import annotations

MINERP_INTERNAL_SHOP_CATALOG_KEY = "minerp_internal_shop"
MINERP_INTERNAL_SHOP_URL = "minerp-internal://minerp_internal_shop"
DEFAULT_ORG_CONNECTION_NAME = "shop-catalog"
DEFAULT_ORG_CONNECTION_LABEL = "Shop catalog CSKH"

SHOP_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "search_shop_products",
        "lookup_shop_order",
        "lookup_shop_product",
        "list_shop_bestsellers",
    }
)


def is_minerp_internal_url(url: str) -> bool:
    return (url or "").strip().lower().startswith("minerp-internal://")


def is_minerp_internal_shop_connection(*, url: str, catalog_key: str | None) -> bool:
    if catalog_key == MINERP_INTERNAL_SHOP_CATALOG_KEY:
        return True
    normalized = (url or "").strip().lower()
    return normalized == MINERP_INTERNAL_SHOP_URL.lower() or normalized.endswith(
        f"/{MINERP_INTERNAL_SHOP_CATALOG_KEY}"
    )
