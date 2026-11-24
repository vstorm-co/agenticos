"""Eval tool tuning capability - score a tool against judged eval cases."""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.eval_tool_tuning._capability import (
    EVAL_TOOL_TUNING_RECORDER_RESOURCE,
    EvalToolTuning,
)
from app.agents.manifest import RunRecorder

__all__ = [
    "EVAL_TOOL_TUNING_RECORDER_RESOURCE",
    "EvalToolTuning",
    "EvalToolTuningConfig",
]


class EvalToolTuningConfig(BaseModel):
    """How many tuning runs one run may record."""

    max_tuning_runs: int = Field(
        title="Tuning runs at most",
        default=3,
        ge=1,
        le=5,
        description=(
            "How many tuning runs one run may record. A fresh tuning run "
            "after a proposal is applied is a new run, and the cap is what "
            "stops repeated scoring turning into scope creep."
        ),
    )


@register(
    id="eval_tool_tuning",
    name="Eval tool tuning",
    category="analysis",
    description=(
        "Score one tool against eval cases that are already judged, classify "
        "each failure, and draft one tuning proposal per failure class - "
        "prompt wording, tool parameters, or tool choice - recorded on the "
        "run manifest as drafts for a human to approve."
    ),
    tools=(
        CapabilityToolInfo(
            id="record_eval_tool_tuning",
            description="Score one tool against judged eval cases and draft tuning proposals.",
        ),
    ),
    config_schema=EvalToolTuningConfig,
    side_effecting=False,
)
def _build(ctx: CapabilityBuildContext) -> EvalToolTuning:
    """Build eval tool tuning from its validated config and the run's recorder."""
    config = ctx.config if isinstance(ctx.config, EvalToolTuningConfig) else None
    recorder = ctx.resources.get(EVAL_TOOL_TUNING_RECORDER_RESOURCE)
    return EvalToolTuning(
        max_tuning_runs=config.max_tuning_runs if config is not None else 3,
        recorder=recorder if isinstance(recorder, RunRecorder) else RunRecorder(),
    )
