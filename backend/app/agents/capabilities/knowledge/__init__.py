"""Knowledge capability — search the collections an agent is bound to."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.knowledge._capability import Knowledge, KnowledgeConfig

__all__ = ["Knowledge", "KnowledgeConfig"]


@register(
    id="knowledge",
    name="Knowledge search",
    category="knowledge",
    description="Search the collections this agent is connected to and cite the sources.",
    # Declared under the id approval is keyed by. A binding may rename it for
    # its own model through `tool_overrides`; the gate resolves the id back to
    # that name, so the two cannot disagree.
    tools=(
        CapabilityToolInfo(
            id="search_documents",
            description=(
                "Search the organization's documents for passages relevant to a question."
            ),
        ),
    ),
    config_schema=KnowledgeConfig,
    scopes=("knowledge:read",),
)
def _build(ctx: CapabilityBuildContext) -> Knowledge | None:
    """Build the capability, or nothing when no collection is bound.

    An agent with knowledge search but no collections would advertise a tool
    that always returns empty — worse than not having it, because the model
    keeps trying.
    """
    if not ctx.resources.get("kb_collection_names"):
        return None
    config = ctx.config if isinstance(ctx.config, KnowledgeConfig) else KnowledgeConfig()
    return Knowledge(default_top_k=config.default_top_k)
