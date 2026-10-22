"""Follow-ups capability - next steps as buttons under an answer."""

from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.follow_ups._capability import FollowUps, kept_steps
from app.agents.capabilities.follow_ups._toolset import FollowUpsToolset

__all__ = [
    "FOLLOW_UPS_CAPABILITY_ID",
    "FOLLOW_UPS_MODEL_RESOURCE",
    "FollowUps",
    "FollowUpsConfig",
    "FollowUpsToolset",
    "kept_steps",
]

FOLLOW_UPS_CAPABILITY_ID = "follow_ups"

FOLLOW_UPS_MODEL_RESOURCE = "follow_ups_model"
"""The built model that writes the next steps, resolved by the runner from
`model_profile_id` - building one needs the database and the vault, which a
capability builder does not have."""


class FollowUpsConfig(BaseModel):
    """How the next steps are written."""

    model_profile_id: UUID | None = Field(
        title="Model for next steps",
        default=None,
        description=(
            "A model profile that writes the next steps once the answer is in, instead of "
            "the agent's own model offering them as a tool. A small, cheap model is enough "
            "for three short buttons, and the agent no longer spends a request on them. "
            "Empty lets the agent offer them itself."
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
            description="Offer up to three next steps as buttons under your answer.",
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
    model = ctx.resources.get(FOLLOW_UPS_MODEL_RESOURCE)
    return FollowUps(model=model if isinstance(model, Model) else None)
