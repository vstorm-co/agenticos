"""Council capability - three delegates review the work, in parallel."""

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.council._capability import (
    COUNCIL_MODELS_RESOURCE,
    COUNCIL_RECORDER_RESOURCE,
    Council,
    resolve_members,
)
from app.agents.manifest import RunRecorder

__all__ = [
    "COUNCIL_MODELS_RESOURCE",
    "COUNCIL_RECORDER_RESOURCE",
    "Council",
    "CouncilConfig",
    "CouncilMemberConfig",
]


class CouncilMemberConfig(BaseModel):
    """One delegate on the council: a name, a provider, and its model."""

    name: str = Field(
        title="Name",
        description="What the delegate is called in the review table, e.g. 'Claude Opus'",
        min_length=1,
        max_length=64,
    )
    provider: str = Field(
        title="Provider",
        description="Which provider this delegate runs on, e.g. 'anthropic'",
        min_length=1,
        max_length=64,
    )
    model_profile_id: UUID = Field(
        title="Model profile",
        description="The model profile this delegate reviews on - its primary model only, never a fallback",
    )


class CouncilConfig(BaseModel):
    """How the council reviews: who sits on it, and when it is satisfied."""

    members: list[CouncilMemberConfig] = Field(
        title="Council members",
        description=(
            "The delegates, one strong model from each of three different "
            "providers at high reasoning effort. Exactly three members."
        ),
        min_length=3,
        max_length=3,
    )
    agreement_threshold: int = Field(
        title="Agreement threshold",
        default=8,
        ge=1,
        le=10,
        description=(
            "The score out of 10 every delegate must reach for a round to "
            "satisfy the council. A round below it means fix and review again."
        ),
    )
    max_rounds: int = Field(
        title="Rounds at most",
        default=3,
        ge=1,
        le=5,
        description=(
            "How many review rounds one run may ask for. A fresh review after "
            "fixes is a new round, and the cap is what stops repeated reviews "
            "turning into scope creep."
        ),
    )

    @model_validator(mode="after")
    def require_distinct_providers(self) -> CouncilConfig:
        providers = {member.provider for member in self.members}
        if len(providers) != 3:
            raise ValueError("Council members must use three distinct providers")
        return self


@register(
    id="council",
    name="Council",
    category="analysis",
    description=(
        "Three delegate reviewers, one strong model from each of three different "
        "providers, score the work out of 10 in parallel rounds until all agree."
    ),
    tools=(
        CapabilityToolInfo(
            id="run_council_review",
            description="Run one council review round over the work.",
        ),
    ),
    config_schema=CouncilConfig,
    scopes=("agents:delegate",),
    side_effecting=False,
    voice="hand_off",
)
def _build(ctx: CapabilityBuildContext) -> Council:
    """Build the council from its validated config and resolved models."""
    config = ctx.config if isinstance(ctx.config, CouncilConfig) else None
    members = (
        resolve_members(
            [member.model_dump() for member in config.members],
            ctx.resources.get(COUNCIL_MODELS_RESOURCE),
        )
        if config is not None
        else []
    )
    recorder = ctx.resources.get(COUNCIL_RECORDER_RESOURCE)
    return Council(
        members=members,
        threshold=config.agreement_threshold if config is not None else 8,
        max_rounds=config.max_rounds if config is not None else 3,
        recorder=recorder if isinstance(recorder, RunRecorder) else RunRecorder(),
    )
