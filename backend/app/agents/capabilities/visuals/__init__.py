"""Visuals capability - the agent draws diagrams, explainers and 3D scenes in the chat."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.visuals._capability import Visuals

__all__ = ["BOUND_CAPABILITIES_RESOURCE", "VISUALS_CAPABILITY_ID", "Visuals"]

VISUALS_CAPABILITY_ID = "visuals"

BOUND_CAPABILITIES_RESOURCE = "bound_capability_ids"
"""Key the factory puts the agent's switched-on capability ids under.

Read here to tell whether the agent may already reach the web, which decides
whether a drawing may fetch an image by address.
"""

_WEB_READERS = frozenset({"web_fetch", "browser_use"})


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
    bound = ctx.resources.get(BOUND_CAPABILITIES_RESOURCE) or frozenset()
    return Visuals(fetches_web=bool(_WEB_READERS & set(bound)))
