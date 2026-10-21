"""Visuals capability - the agent draws diagrams, explainers and 3D scenes in the chat."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.visuals._capability import Visuals
from app.agents.capabilities.visuals._reach import WEB_REACH_RESOURCE, web_reach

__all__ = ["VISUALS_CAPABILITY_ID", "WEB_REACH_RESOURCE", "Visuals", "web_reach"]

VISUALS_CAPABILITY_ID = "visuals"


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
    ),
)
def _build(ctx: CapabilityBuildContext) -> Visuals:
    return Visuals(web_reach=ctx.resources.get(WEB_REACH_RESOURCE) or ())
