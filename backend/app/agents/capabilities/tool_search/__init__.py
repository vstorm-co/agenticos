"""Tool search capability - discover a tool rather than carry its schema."""

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import ToolSearch

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.tool_search._capability import (
    ConfiguredToolSearch,
    Strategy,
    build_tool_search,
)

__all__ = ["ConfiguredToolSearch", "ToolSearchConfig", "build_tool_search"]


class ToolSearchConfig(BaseModel):
    """How the agent finds the tools it is not shown up front."""

    strategy: Strategy = Field(
        title="Search method",
        default="auto",
        description=(
            "auto: native tool search on a provider that supports it, local "
            "keyword matching elsewhere. "
            "keywords: always match locally, on any provider. "
            "local_bm25: rank identifiers, descriptions and arguments locally on any provider. "
            "bm25 / regex: force an Anthropic-native algorithm; errors on a "
            "provider that has no native tool search."
        ),
    )
    max_results: int = Field(
        title="Matches per search",
        default=10,
        ge=1,
        le=50,
        description="How many matches the local search returns; ignored for native search.",
        json_schema_extra={"x-advanced": True},
    )
    defer_capabilities: bool = Field(
        default=False,
        title="Defer capability tools",
        description=(
            "Hide eligible tools from enabled capabilities until the agent searches for them. "
            "Off keeps capability tools visible."
        ),
    )
    defer_mcp_servers: bool = Field(
        default=True,
        title="Defer MCP tools",
        description=(
            "Hide eligible tools from bound MCP servers until the agent searches for them. "
            "Off keeps MCP tools visible."
        ),
    )
    exclude_capabilities: list[str] = Field(
        default_factory=list,
        title="Always-visible capabilities",
        description=(
            "Comma-separated capability IDs whose tools stay visible, such as knowledge or visuals. "
            "These capabilities must still be enabled."
        ),
    )
    exclude_mcp_servers: list[str] = Field(
        default_factory=list,
        title="Always-visible MCP servers",
        description=(
            "Comma-separated MCP tool namespace prefixes whose tools stay visible, such as github_work or agenticos. "
            "Use the prefix before the tool name, with hyphens replaced by underscores."
        ),
    )
    exclude_tools: list[str] = Field(
        default_factory=list,
        title="Always-visible tools",
        description=(
            "Comma-separated model-facing tool names to keep visible. Use renamed capability tool names "
            "and fully prefixed MCP tool names, such as github_work_list_issues."
        ),
    )


@register(
    id="tool_search",
    name="Tool search",
    category="utility",
    description=(
        "Let the agent find the right tool from a large set instead of carrying "
        "every tool's schema in its context. Defer tools from enabled capabilities, "
        "bound MCP servers or both, with exclusions that keep selected tools visible."
    ),
    # No tools by design: `ToolSearch` contributes its `search_tools` function
    # only once it wraps a toolset that has deferred tools, which the factory
    # arranges. In isolation it resolves to no toolset at all, so there is
    # nothing here to declare, gate or rename. See `tool_search/_capability.py`
    # and `factory._defer_for_tool_search`.
    tools=(),
    config_schema=ToolSearchConfig,
)
def _build(ctx: CapabilityBuildContext) -> ToolSearch[object]:
    config = ctx.config if isinstance(ctx.config, ToolSearchConfig) else ToolSearchConfig()
    return build_tool_search(
        config.strategy,
        config.max_results,
        defer_capabilities=config.defer_capabilities,
        defer_mcp_servers=config.defer_mcp_servers,
        exclude_capabilities=frozenset(config.exclude_capabilities),
        exclude_mcp_servers=frozenset(config.exclude_mcp_servers),
        exclude_tools=frozenset(config.exclude_tools),
    )
