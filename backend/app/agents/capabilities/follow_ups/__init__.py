"""Follow-ups capability - next steps as buttons under an answer."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.follow_ups._capability import FollowUps
from app.agents.capabilities.follow_ups._toolset import FollowUpsToolset

__all__ = ["FOLLOW_UPS_CAPABILITY_ID", "FollowUps", "FollowUpsToolset"]

FOLLOW_UPS_CAPABILITY_ID = "follow_ups"


@register(
    id=FOLLOW_UPS_CAPABILITY_ID,
    name="Follow-ups",
    category="utility",
    description=(
        "Offer the person up to three next steps as buttons under an answer, "
        "so what to ask next is one click away."
    ),
    tools=(
        CapabilityToolInfo(
            id="suggest_next_steps",
            description="Offer up to three next steps as buttons under your answer.",
        ),
    ),
    # A call has no buttons to put them on, and reading three steps aloud after
    # every answer is the closing paragraph this exists to replace.
    voice="never",
)
def _build(ctx: CapabilityBuildContext) -> FollowUps:
    return FollowUps()
