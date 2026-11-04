"""Follow-ups capability - next steps as buttons under an answer."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.follow_ups._capability import FollowUps, kept_steps
from app.agents.capabilities.follow_ups._toolset import FollowUpsToolset

__all__ = [
    "FOLLOW_UPS_CAPABILITY_ID",
    "FollowUps",
    "FollowUpsConfig",
    "FollowUpsToolset",
    "kept_steps",
]

FOLLOW_UPS_CAPABILITY_ID = "follow_ups"


class FollowUpsConfig(BaseModel):
    """How the next steps are written."""

    model_profile_id: UUID | None = Field(
        title="Model for next steps",
        default=None,
        description=(
            "A separate model profile that writes next-step buttons in the background after "
            "the answer is saved. It never delays the answer or the next message. "
            "A small, cheap model is enough. Empty disables next-step suggestions."
        ),
        json_schema_extra={"x-widget": "model-profile"},
    )


@register(
    id=FOLLOW_UPS_CAPABILITY_ID,
    name="Follow-ups",
    category="utility",
    description=(
        "Offer the person up to three next steps as buttons under an answer, and things "
        "to set up as cards, so what to do next is one click away."
    ),
    tools=(
        CapabilityToolInfo(
            id="suggest_next_steps",
            # Historical identity for persisted buttons and existing spec overrides.
            description="Next-step buttons generated after the answer by a separate model.",
        ),
        CapabilityToolInfo(
            id="propose_setup",
            description=(
                "Propose up to three concrete things to set up, as cards the person acts on "
                "in one click."
            ),
        ),
    ),
    # A call has no buttons to put them on, and reading three steps aloud after
    # every answer is the closing paragraph this exists to replace.
    voice="never",
    config_schema=FollowUpsConfig,
)
def _build(ctx: CapabilityBuildContext) -> FollowUps:
    return FollowUps()
