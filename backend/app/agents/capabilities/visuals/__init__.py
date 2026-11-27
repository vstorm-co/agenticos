"""Visuals capability - the agent draws diagrams, explainers and 3D scenes in the chat."""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.visuals._capability import Visuals
from app.agents.capabilities.visuals._reach import WEB_REACH_RESOURCE, web_reach

__all__ = ["VISUALS_CAPABILITY_ID", "WEB_REACH_RESOURCE", "Visuals", "VisualsConfig", "web_reach"]

VISUALS_CAPABILITY_ID = "visuals"


class VisualsConfig(BaseModel):
    """How a visual's preview comes back to the model."""

    preview_screenshot: bool = Field(
        default=True,
        title="Show the model a visual's picture",
        description=(
            "Return a screenshot when the agent previews a visual. Turn off for a model "
            "that cannot read images; rendering diagnostics still come back."
        ),
    )


@register(
    id=VISUALS_CAPABILITY_ID,
    name="Visuals",
    category="analysis",
    description=(
        "Let the agent draw in the conversation - a diagram, an architecture map, a flow, an "
        "interactive explainer, a 3D scene. The drawing appears live under its message while "
        "it is written, stays in the conversation, and can be saved as an app."
    ),
    tools=(
        CapabilityToolInfo(
            id="draw",
            description=(
                "Draw a picture in the conversation: a diagram, a map, a flow, an explainer, "
                "a 3D scene."
            ),
        ),
        CapabilityToolInfo(
            id="revise_visual",
            description="Change a visual by exact replacements, without drawing it again.",
        ),
        CapabilityToolInfo(
            id="read_visual",
            description="Read a visual in this conversation as it now is, revisions applied.",
        ),
        CapabilityToolInfo(
            id="preview_visual",
            description="Inspect a visual in this conversation: a screenshot and rendering diagnostics.",
            read_only=True,
        ),
    ),
    config_schema=VisualsConfig,
)
def _build(ctx: CapabilityBuildContext) -> Visuals:
    config = ctx.config if isinstance(ctx.config, VisualsConfig) else VisualsConfig()
    return Visuals(
        web_reach=ctx.resources.get(WEB_REACH_RESOURCE) or (),
        screenshot=config.preview_screenshot,
    )
