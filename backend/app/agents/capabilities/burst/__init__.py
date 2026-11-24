"""Burst capability - split one task into parallel subtasks and merge them."""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.burst._capability import (
    BURST_RECORDER_RESOURCE,
    Burst,
)
from app.agents.manifest import RunRecorder

__all__ = [
    "BURST_RECORDER_RESOURCE",
    "Burst",
    "BurstConfig",
]


class BurstConfig(BaseModel):
    """How a burst splits: how many parts at once, and how many bursts a run."""

    max_subtasks: int = Field(
        title="Subtasks at most",
        default=3,
        ge=2,
        le=10,
        description=(
            "How many subtasks one burst runs at once. 3 is the subagents "
            "max_fanout default and 10 its hard max: a burst shares that "
            "ceiling rather than raising it. Reached, the tool refuses the "
            "extra parts with a message the model can act on."
        ),
    )
    max_bursts: int = Field(
        title="Bursts at most",
        default=3,
        ge=1,
        le=5,
        description=(
            "How many bursts one run may ask for. A fresh burst after fixes "
            "is a new burst, and the cap is what stops repeated bursts "
            "turning into scope creep."
        ),
    )


@register(
    id="burst",
    name="Burst",
    category="analysis",
    description=(
        "Split one task into independent subtasks, run them in parallel, and "
        "merge the results into one outcome - a burst of parallel work "
        "instead of one sequential run."
    ),
    tools=(
        CapabilityToolInfo(
            id="run_burst",
            description="Split a task into parallel subtasks and merge the results.",
        ),
    ),
    config_schema=BurstConfig,
    scopes=("agents:delegate",),
    side_effecting=False,
    voice="hand_off",
)
def _build(ctx: CapabilityBuildContext) -> Burst:
    """Build the burst from its validated config and the run's recorder."""
    config = ctx.config if isinstance(ctx.config, BurstConfig) else None
    recorder = ctx.resources.get(BURST_RECORDER_RESOURCE)
    return Burst(
        max_subtasks=config.max_subtasks if config is not None else 3,
        max_bursts=config.max_bursts if config is not None else 3,
        recorder=recorder if isinstance(recorder, RunRecorder) else RunRecorder(),
    )
