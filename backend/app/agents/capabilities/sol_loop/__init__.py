"""Sol-loop capability - one reviewer judges the work, in rounds."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.sol_loop._capability import (
    SOL_LOOP_MODELS_RESOURCE,
    SOL_LOOP_RECORDER_RESOURCE,
    SolLoop,
    resolve_reviewer,
)
from app.agents.manifest import RunRecorder

__all__ = [
    "SOL_LOOP_MODELS_RESOURCE",
    "SOL_LOOP_RECORDER_RESOURCE",
    "SolLoop",
    "SolLoopConfig",
    "SolLoopReviewerConfig",
]


class SolLoopReviewerConfig(BaseModel):
    """The loop's one reviewer: a name, a provider, and its model."""

    name: str = Field(
        title="Name",
        description="What the reviewer is called in the review ledger, e.g. 'GPT Sol'",
        min_length=1,
        max_length=64,
    )
    provider: str = Field(
        title="Provider",
        description="Which provider this reviewer runs on, e.g. 'openai'",
        min_length=1,
        max_length=64,
    )
    model_profile_id: UUID = Field(
        title="Model profile",
        description=(
            "The model profile this reviewer reviews on - its primary model only, "
            "never a fallback. Point it at your Sol model."
        ),
    )


class SolLoopConfig(BaseModel):
    """How sol-loop reviews: who reviews, and how many rounds it may take."""

    reviewer: SolLoopReviewerConfig = Field(
        title="Reviewer",
        description="The one reviewer that judges the work, on its Sol model.",
    )
    max_rounds: int = Field(
        title="Rounds at most",
        default=3,
        ge=1,
        le=5,
        description=(
            "How many review rounds one run may ask for. A fresh review after "
            "fixes is a new round, and the cap is what stops repeated reviews "
            "turning into scope creep. Extend to 5 only for security, "
            "permissions, auth, data loss, or state and concurrency, while a "
            "blocker or should stays open - or when the user asks."
        ),
    )


@register(
    id="sol_loop",
    name="Sol-loop",
    category="analysis",
    description=(
        "One reviewer judges the work in rounds until it passes: round 1 reviews "
        "the whole change, later rounds check only changed code and open findings, "
        "with a findings ledger on the run manifest."
    ),
    tools=(
        CapabilityToolInfo(
            id="run_sol_loop_review",
            description="Run one sol-loop review round over the work.",
        ),
    ),
    config_schema=SolLoopConfig,
    scopes=("agents:delegate",),
    side_effecting=False,
    voice="hand_off",
)
def _build(ctx: CapabilityBuildContext) -> SolLoop:
    """Build sol-loop from its validated config and resolved models."""
    config = ctx.config if isinstance(ctx.config, SolLoopConfig) else None
    reviewer = (
        resolve_reviewer(
            config.reviewer.model_dump() if config is not None else None,
            ctx.resources.get(SOL_LOOP_MODELS_RESOURCE),
        )
        if config is not None
        else None
    )
    recorder = ctx.resources.get(SOL_LOOP_RECORDER_RESOURCE)
    return SolLoop(
        reviewer=reviewer,
        max_rounds=config.max_rounds if config is not None else 3,
        recorder=recorder if isinstance(recorder, RunRecorder) else RunRecorder(),
    )
