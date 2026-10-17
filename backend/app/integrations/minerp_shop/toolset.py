"""In-process MCP toolset for minerp_internal_shop."""

from __future__ import annotations

from typing import Any

from pydantic_ai.toolsets import FunctionToolset

from app.agents.deps import AgentDeps
from app.agents.mcp import tool_prefix
from app.integrations.minerp_shop import tools as shop_tools
from app.integrations.minerp_shop.constants import SHOP_TOOL_NAMES


def internal_shop_tool_infos() -> list[tuple[str, str]]:
    return [
        ("search_shop_products", "Search shop catalog by Vietnamese name or keyword."),
        ("lookup_shop_order", "Look up order by guest status token or order UUID."),
        ("lookup_shop_product", "Look up product by name, SKU, or item UUID."),
        ("list_shop_bestsellers", "Top-selling products from recent WEB orders."),
    ]


def _base_toolset() -> FunctionToolset[AgentDeps]:
    toolset: FunctionToolset[AgentDeps] = FunctionToolset()

    @toolset.tool
    async def search_shop_products(ctx, query: str, limit: int = 5) -> str:
        """Search the shop catalog by product name or keyword (Vietnamese OK)."""
        return await shop_tools.search_shop_products(ctx, query, limit)

    @toolset.tool
    async def lookup_shop_order(ctx, order_ref: str) -> str:
        """Look up order by guest status token or internal order UUID for this shop tenant."""
        return await shop_tools.lookup_shop_order(ctx, order_ref)

    @toolset.tool
    async def lookup_shop_product(ctx, product_ref: str) -> str:
        """Look up a catalog product by name, SKU, or item UUID for this shop tenant."""
        return await shop_tools.lookup_shop_product(ctx, product_ref)

    @toolset.tool
    async def list_shop_bestsellers(ctx, limit: int = 8, days: int = 30) -> str:
        """Top-selling products from real WEB orders in the last N days."""
        return await shop_tools.list_shop_bestsellers(ctx, limit, days)

    return toolset


def build_minerp_internal_shop_toolset(
    *,
    connection_name: str,
    allowed_tools: list[str] | None,
) -> Any:
    """FunctionToolset prefixed like an HTTP MCP connection."""
    toolset = _base_toolset()
    if allowed_tools is not None:
        allowed = set(allowed_tools)
        toolset = toolset.filtered(lambda _ctx, tool: tool.name in allowed)
    prefixed = toolset.prefixed(tool_prefix(connection_name))
    return prefixed.filtered(
        lambda _ctx, tool: any(
            tool.name.endswith(f"__{name}") or tool.name == name for name in SHOP_TOOL_NAMES
        )
    )
