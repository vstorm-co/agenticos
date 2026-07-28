"""Thinking capability - how hard the model reasons before it answers."""

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import Thinking
from pydantic_ai.settings import ThinkingEffort

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.thinking._capability import build_thinking

__all__ = ["ThinkingConfig"]


class ThinkingConfig(BaseModel):
    """How much reasoning to ask the model for."""

    effort: ThinkingEffort | None = Field(
        default=None,
        description=(
            "How hard the model reasons before answering. Leave unset for the "
            "provider's own default effort; a level a provider does not have maps "
            "to its closest one."
        ),
    )


@register(
    id="thinking",
    name="Thinking",
    category="reasoning",
    description=(
        "Let the model reason before it answers - slower and dearer, better on work "
        "that needs several steps held in mind at once."
    ),
    # No tools by design: this changes how the model runs, not what it can do,
    # so there is nothing here for a person to approve.
    tools=(),
    config_schema=ThinkingConfig,
)
def _build(ctx: CapabilityBuildContext) -> Thinking:
    config = ctx.config if isinstance(ctx.config, ThinkingConfig) else ThinkingConfig()
    return build_thinking(config.effort)
