"""Tool search capability - discover a tool rather than carry its schema."""

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import ToolSearch

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.tool_search._capability import Strategy, build_tool_search

__all__ = ["ToolSearchConfig", "build_tool_search"]


class ToolSearchConfig(BaseModel):
    """How the agent finds the tools it is not shown up front."""

    strategy: Strategy = Field(
        default="auto",
        description=(
            "auto: native tool search on a provider that supports it, local "
            "keyword matching elsewhere. "
            "keywords: always match locally, on any provider. "
            "bm25 / regex: force an Anthropic-native algorithm; errors on a "
            "provider that has no native tool search."
        ),
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=50,
        description="How many matches the local search returns; ignored for native search.",
    )


@register(
    id="tool_search",
    name="Tool search",
    category="utility",
    description=(
        "Let the agent find the right tool from a large set instead of carrying "
        "every tool's schema in its context. Hides connected MCP servers' tools "
        "until the agent searches for one."
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
    return build_tool_search(config.strategy, config.max_results)
