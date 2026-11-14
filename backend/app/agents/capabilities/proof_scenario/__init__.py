"""Proof-scenario capability - observed evidence for a change, never a merge."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.proof_scenario._capability import (
    PROOF_SCENARIO_RECORDER_RESOURCE,
    ProofScenarioCapability,
)
from app.agents.manifest import RunRecorder

__all__ = [
    "PROOF_SCENARIO_RECORDER_RESOURCE",
    "ProofScenarioCapability",
]


@register(
    id="proof_scenario",
    name="Proof scenario",
    category="analysis",
    description=(
        "Prove a change with observed evidence: record a reproduction scenario "
        "before the fix and after it, and report which changed files have proof "
        "and which do not. A green unit test never counts as proof."
    ),
    tools=(
        CapabilityToolInfo(
            id="proof_scenario_record",
            description="Record one observed attempt at a proof scenario.",
        ),
        CapabilityToolInfo(
            id="proof_scenario_verdict",
            description="Report which changed files have observed proof, and which do not.",
            read_only=True,
        ),
    ),
    scopes=(),
    side_effecting=False,
    voice="hand_off",
)
def _build(ctx: CapabilityBuildContext) -> ProofScenarioCapability:
    """Build proof-scenario from the run's recorder."""
    recorder = ctx.resources.get(PROOF_SCENARIO_RECORDER_RESOURCE)
    return ProofScenarioCapability(
        recorder=recorder if isinstance(recorder, RunRecorder) else RunRecorder(),
    )
